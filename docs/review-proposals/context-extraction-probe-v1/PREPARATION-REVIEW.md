# Context Extraction V1 — preparation review

**READY FOR SEPARATE EXECUTION DECISION.** Implementation and provider-free preparation are complete. Execution is unauthorized and the required separate authorization file is absent. Preparation made **zero provider requests** and created no semantic measurements or usable evidence.

The accepted 24-case slate is materialized and sealed: 12 adequate contexts (4 G2, 4 current G3, 4 reported G3), six clipped counterparts and six controls. The [source-oracle review](SOURCE-ORACLE-REVIEW.md) records every slot and its qualifications; [source-panel-spec-v1.json](source-panel-spec-v1.json) contains the exact canonical bounds and prospective oracle. All adequate focal/required-source spans fit within their contiguous contexts. No fresh sources or historical expectations were changed.

The unchanged primary criterion is **at least 10/12 adequate contexts recovered and at least 3/4 in each route**, without manual target repair. Clipped and control behavior receives complete diagnostic audit, with **no new numerical gate**. Incomplete review, unresolved context/target sufficiency and saturation retain the accepted HOLD treatment. There is no semantic or containment PASS at preparation.

## Implementation and validation

The extractor proposes spans with local Unicode codepoint offsets and exact text, role shapes, dependency spans, provenance hypotheses and sufficiency hypotheses. Deterministic validation rejects unknown fields, duplicate keys, nonfinite JSON, foreign contexts, noninteger/out-of-range offsets, source-text mismatch, incompatible roles, overlapping G2 roles, declared dependencies outside targets, duplicate provenance dimensions and unsupported nonunknown provenance hypotheses. It never fuzzy-matches or repairs a nomination. Missing undeclared qualifications and semantic/provenance truth still require source review.

Literal-valid records remain typed **untrusted nominations with usable_evidence=false**. The probe imports no semantic interpreter or admission adapter. It cannot create positive facts, local evidence or pastor credit. A neutral complete word-offset map assists exact coordinate selection without supplying selected semantic targets or oracle answers.

Requests, context/source hashes, prompt/schema and implementation/runtime files are fingerprint-bound. Future execution verifies a separate Brian authorization **before credentials or network**, locks the run, reserves each attempt before transport, preserves sealed raw response/request/context/authority bindings, and reuses receipts. An interrupted attempted request without a sealed response is uncertain spend and cannot be retried. HTTP/access/model/usage errors halt; malformed or truncated nominations remain failed raw outputs without repair/retry. Results remain pending a complete source audit. No SDK retries, redirects, endpoint override, tools, automatic expansions or model substitution are enabled.

Focused verification: **42 tests passed**, covering literal/Unicode/role/dependency checks, immutable serialization, authorization order, synthetic receipt/recovery and token/model/HTTP failure paths, plus historical design/CLI contracts. The real CLI check verifies sealed source/context/oracle/request/implementation/tokenizer bindings. Tests used synthetic transport only. No large fixture/corpus job was run.

## Single-model and request lock

- Model: **`gpt-5.4-mini-2026-03-17`**, direct Chat Completions HTTPS via pinned httpx; one snapshot, one prompt, no comparison.
- Strict JSON schema; `reasoning_effort=none`, `temperature=0`, `top_p=1`, `n=1`, `max_completion_tokens=2048`, standard/default service tier, `stream=false`, `store=false`; no tools or seed.
- Frozen [prompt](prompt-v1.txt), [schema](schema-v1.json), [model lock](model-lock-v1.json), and [runtime lock](runtime-lock-v1.json).
- Isolated tiktoken 0.12.0 / regex 2025.11.3 / o200k_base table, installed and hash-verified for **local token accounting only**. No extractor weights were downloaded or loaded; no inference was performed. Shared environment packages were not replaced.
- Fixed parameters are not a provider determinism guarantee. The receipt retains the raw response including any returned system fingerprint. Account access and live structured-output compatibility have not been tested; a rejection stops without substitution or retry.

## Tokens, cost and review budget

The local tokenizer counts the **entire serialized request**, including prompt, source, complete neutral word-offset map and schema. Total local count: **55,170 tokens**; largest request: **5,218**. A further 4,096 framing tokens per request gives **153,474 reserved input tokens**, largest reservation **9,314**, below 16,384/request and 393,216 total. These are exact counts for the pinned local encoding and serialized payload, **not exact provider billing tokens**. OpenAI's API does not expose an input-token cap parameter here; conservative headroom is a client preflight. An actual usage overrun halts subsequent calls but cannot undo a completed request. This residual accounting uncertainty is preserved.

The ceiling uses all authorized tokens, not the smaller local count: input `393216 × $0.75 / 1M = $0.294912`; output/reasoning `49152 × $4.50 / 1M = $0.221184`; **total $0.516096** at the locked model list price, without caching discounts. This is below the approved **$5** exposure. Each attempt reserves 16,384 input / 2,048 output and $0.021504; 24 attempts maximum, no retries or context expansions. Actual usage, refusals, finish reasons and response identity are retained.

Official sources checked for the lock: [model snapshot and prices](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), and [Chat Completions parameters](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create). Repricing or incompatible API behavior requires a new decision rather than silently altering this packet.

Active source-review budget: conservatively charge 60 minutes for preparation, leaving **420 minutes** of the authorized 480 for the later complete audit. This is a budget charge, not measured review throughput. Log actual active post-run review; exhaustion/incomplete audit means HOLD. Brian is not assigned annotation or case preparation.

## Seals and command

Input fingerprint: `54ada40ca8926a6bae0a89cd41c091fcc0ce9e31c3c4cc27969feee892e7a76a`

Panel fingerprint: `ed31ec621466774c9cb3677a11092216b3acba457d95abdea5384015ed21face`

Source-oracle fingerprint: `8a73d6f8388b278b18dbb8690caaad656fd6b9b2c6b29b24c62f7b4d62506d83`

The [input manifest](input-manifest-v1.json) binds the generated request input in the application's evaluation directory. Raw prepared contexts, requests and future receipts stay outside Git. [implementation-review-v1.json](implementation-review-v1.json) records all 24 context/request fingerprints, token counts and preserved decisions.

Read-only review command:

```bash
pte analysis collector-retrieval-design --context-extraction-probe --check-only
```

**After separate authorization is recorded**, Brian's exact execution command will be:

```bash
pte analysis collector-retrieval-design --context-extraction-probe --run --approve-input 54ada40ca8926a6bae0a89cd41c091fcc0ce9e31c3c4cc27969feee892e7a76a
```

`--approve-input` verifies identity; it does not grant authorization. The command is blocked while `execution-authorization-v1.json` is absent. No extractor run has been started.

## Recommendation and limits

Recommend separately authorizing this exact bounded nomination-feasibility experiment. After Brian executes it, Codex must audit every output, missing focal opportunity, qualifier/provenance difference, clipped case and control against the sealed oracle and full source. Record unsupported positives, conservative withholding, unresolved cases and saturation separately; do not repair targets or claim containment. Any measurement/admission adapter is a separate prospective proposal.

The oracle is source-controlled, single-reviewer and not an accepted receipt-bound admission witness. Adequate contexts are oracle-assisted and the word map supplies coordinate navigation. This establishes no natural retrieval recall, fresh-source generalization, production containment, automated provenance, review throughput, unit economics, recurrence/rates or pastor profile.

V1.1 remains closed as development FAIL; G1 remains HOLD; V4 raw FAIL / containment HOLD and bounded A1 PASS remain unchanged. No Jev run, G1/G2/G3/P1/A1/threshold change, collector reopening, fresh-source selection, 790-item audit, collection, production activation, projection/comparison/scoring or downstream usable evidence is authorized.
