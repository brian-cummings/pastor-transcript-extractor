# Authorized V4 semantic run — Brian executes

**Brian authorizes only the frozen 24-case / maximum 37-request panel. Codex has not executed it.** The [execution authorization](execution-authorization-v4.json) supersedes the historical execution hold in the frozen input and implementation review; the input itself is unchanged. This sidecar authorizes spending, not the preliminary source oracle or any future review witness.

Input fingerprint: `3deba35907971549e9693c170e53ace6c8e3444b447a1715c5fd28501c7a893c`.

```sh
pte analysis evidence-supply-boundary-revalidation --paid-run-preflight
pte analysis evidence-supply-boundary-revalidation --execute \
  --approve-paid-packet 3deba35907971549e9693c170e53ace6c8e3444b447a1715c5fd28501c7a893c
```

The fixed run retains Jev 1.13.0, all frozen request states/questions/options, the original selected-option probability >= .80 gate, zero automatic retries, long context off, and cumulative ceilings of **37 attempts / 2,368,000 input tokens / $0.099456 model list price**. Every attempt reserves 64,000 input tokens and $0.002688 before sending. Actual token usage is reported separately. Brian's existing `TYPESAFE_API_KEY` is used only when a new request is actually needed; checks and receipt replay do not construct a provider.

Runtime directory is bound by the authorization to:

```text
/Users/briancummings/Documents/PastorSearchData/evaluation/evidence-supply-boundary-v4
```

It contains `request-ledger.json`, `receipts/<request-key>.json`, `results-v4.json`, `results-v4.md`, and an execution lock. Runtime artifacts stay outside the repository. The bound directory prevents an alternate base directory from silently creating another spending allowance. Moving the ledger or changing the authorized location requires a separate concrete recovery decision.

The runner prints before and after every request and prints the final result paths. It holds a process lock, atomically persists and syncs charged reservations before sending, and persists sealed raw reply bytes before parsing or interpretation. There is no SDK retry or redirect replay. A failed/invalid/lost reply keeps its reservation, stops the run and requires a separate recovery decision; the same CLI command cannot replace that attempt automatically. Do not delete the ledger or receipts to retry. A valid saved identical-state receipt is reused locally without spending, including recovery after interruption between receipt persistence and ledger validation. V3/foreign/orphan/corrupt receipts are rejected. Finished raw-result reports can be regenerated from valid receipts without provider calls; a completed-results/ledger mismatch stops instead of creating new allowance.

## After execution

Brian supplies the completion or error output. Codex does not run or monitor the job. On completion Codex owns the full source audit: every positive field, every historical/forward difference and every unscored failure against exact supplied state and full frozen source. Raw bytes, raw distributions, selected probability, confidence and gated decisions remain separate and immutable.

The initial results deliberately have no accepted receipt-bound source review. All preliminary admissions are therefore quarantined. This is not a semantic failure, a successful containment test, or an accepted witness. Codex prepares the source review bound to actual measurements and receipts, then separate **raw-semantic** and **containment** recommendations under [the frozen V4 criteria](CRITERIA-v4.md). Brian accepts/rejects the concrete decisions. A source audit may reject/withhold a raw answer; it cannot rewrite that answer into compatible evidence.

Any unsupported admitted item means containment FAIL. Conservative quarantine alone is not failure. Positive compatible G2, current-preacher G3 and reported-local G3 evidence is still required to avoid a vacuous all-reject PASS. Do not start a V5 or tune Jev merely because raw answers contain errors; assess semantic accuracy and enforced containment separately.

No G1/G2/G3 contract or threshold changes, ranker work, automatic attestation, discovery, broader collection, 790-item non-reference V2 audit, production use, recurrence/rates, or pastor projection/comparison/scoring are authorized. Source review remains a bounded safety oracle; production provenance resolution and review throughput remain unestablished.
