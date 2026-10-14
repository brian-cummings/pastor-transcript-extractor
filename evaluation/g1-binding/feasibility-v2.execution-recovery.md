# G1 V2 interrupted-run diagnosis and proposed recovery

## G1 V2 execution recovery proposed — 2026-10-14

Brian's V2 run stopped at **B03:unit-0** with `Malformed Choice answer`.
There are **30 charged attempts, 29 validated saved responses, eight outstanding
candidates and seven remaining attempts** under the original 37-request ceiling.
This is incomplete execution, **not a semantic V2 verdict or acceptance**.
The original failed response was not persisted; its exact validation failure cannot
be reconstructed. A confirmed floating point boundary defect can reject mass `.99`
at the existing `.01` tolerance, but it cannot be identified as B03's cause without
the lost response. No answer is fabricated or repaired by normalization.

The execution repair is committed as `0d79a6b`: preserve returned raw response receipts
before validation, report field-specific contract failures, accept floating point
edges at the existing mass tolerance, and preflight all cached answers and remaining
budget before constructing the provider. The `.80` decision threshold, four V2
semantic questions, frozen cases/expectations, V1 sources and composition remain
unchanged. Invalid receipts stop locally rather than silently triggering new calls.
Thirteen focused V2 tests, nine frozen V1 tests, 18 CLI contract tests and five CLI
reference tests pass. Read-only integrity checks validate the actual 29 caches and
original ledger prefix. No provider calls or live-ledger modifications were made by
Codex during this repair.

**Proposed, not yet authorized/executed:** one replacement for the lost response.
Brian can explicitly approve the cumulative ceiling change **37 → 38** by running:

```sh
pte analysis g1-feasibility-review --revision v2 --replace-lost-response
```

This requires the exact original first 30 attempt records, reuses the 29 responses
and sends at most eight additional requests (one replacement plus seven never sent).
It retains the failed attempt and its token usage. It is not a general retry switch.
The frozen packet still records its original 37 ceiling; any final result separately
records the effective 38 ceiling and explicit replacement authorization. Without
this opt-in the original command stops before spending because the remaining budget
cannot finish. Do not reset/delete the ledger or caches. A further failure requiring
more spending must return for review; no automatic allowance is provided.

The [execution diagnosis](feasibility-v2.execution-recovery.md)
and [JSON snapshot](feasibility-v2.execution-recovery.json)
preserve the incomplete-run facts and proposed recovery separately from semantic
results. A future agent must check whether Brian has since executed the opt-in and
read `evaluation/g1-binding/feasibility-v2.results.md` / `.json` if present. Original
`execution-failure` and `execution-recovery` artifacts are historical snapshots,
not later result status. Replays after an approved replacement use the same flag.
After execution, interpret corrected failures, legitimate withholding, remaining
systematic errors and disputed expectations against the unchanged source/oracle;
recommend only whether bounded G1 local-proposition feasibility can close, and stop.
All previously held collection, projection/comparison, clustering, contradiction/
coherence/G4, recall, calibration, denominators/economics studies, rates and scoring
remain held. No V3, corpus expansion or new semantic refinement is authorized.

