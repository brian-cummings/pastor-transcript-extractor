# Context Extraction V1 — authorized execution handoff

**AUTHORIZED — ready for Brian to execute once.** Brian explicitly authorized the frozen 24-context experiment in the current chat. [execution-authorization-v1.json](execution-authorization-v1.json) records that separate decision; [execution-handoff-v1.json](execution-handoff-v1.json) binds the preparation packet, every request/context fingerprint, and the verified authorization.

Input fingerprint: `54ada40ca8926a6bae0a89cd41c091fcc0ce9e31c3c4cc27969feee892e7a76a`.

The frozen implementation, input, prompt/schema, runtime, model lock, source contexts and prospective oracle are unchanged. The preparation report and `--check-only` output describe the historical preparation state and still say authorization is required. They have not been rewritten. The actual execution gate now verifies the separate **AUTHORIZED** decision against the exact input fingerprint and limits.

Read-only verification passed for the source/context/oracle/request/tokenizer/implementation seals. All 16 focused probe tests passed with synthetic transport only. The authorization gate accepted the recorded decision. No API credential was inspected, no network inference was attempted, and no execution attempts, receipts or results exist.

Project `AGENTS.md` assigns validation execution to Brian and interpretation/source audit to Codex. This handoff implements that division without another approval gate.

Run once, with `OPENAI_API_KEY` already available in the shell environment:

```bash
pte analysis collector-retrieval-design --context-extraction-probe --run --approve-input 54ada40ca8926a6bae0a89cd41c091fcc0ce9e31c3c4cc27969feee892e7a76a
```

Do not alter parameters or retry after a failure. An attempt without a sealed receipt represents uncertain spend and cannot be retried. The implementation reuses sealed responses when available and never grants a second provider request for an attempted context. Compatibility failures stop the run; raw nomination failures remain disclosed without target repair. No automatic downstream semantic/admission execution follows.

The locked model remains `gpt-5.4-mini-2026-03-17`; at most 24 requests and four nominations/context; zero retries or expansions; 16,384 reserved input and 2,048 output/reasoning tokens/request; total limits 393,216 input and 49,152 output/reasoning tokens. The model list-price ceiling remains **$0.516096**, within the authorized $5 exposure. Offline token reservations are not guaranteed provider billing counts; the preparation review preserves that limitation.

Results and raw receipts will be sealed under:

`/Users/briancummings/Documents/PastorSearchData/evaluation/context-extraction-probe-v1/54ada40ca8926a6bae0a89cd41c091fcc0ce9e31c3c4cc27969feee892e7a76a/`

After execution, Codex owns the complete source audit against the sealed oracle and full source within the remaining **420 active review minutes**. Audit every raw nomination, omitted focal opportunity, clipped case, control, qualifier/provenance discrepancy, unsupported output and saturation event. No manual target repair credit is permitted. The frozen primary criterion remains **at least 10/12 adequate contexts and at least 3/4 in each route**. Clipped/control behavior has no new numerical gate. Unknowns and incomplete review remain unresolved/HOLD.

Return the sealed execution result and complete audit before proposing another experiment. Any success is **nomination feasibility only**, establishing no retrieval recall, containment, usable evidence, provenance automation, collection readiness, production or pastor-level analysis. Jev, adapters, fresh sources, collector reopening, semantic/threshold changes, collection and projection/comparison/scoring remain unauthorized.
