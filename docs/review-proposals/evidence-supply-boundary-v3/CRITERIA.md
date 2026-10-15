# Small V3 semantic boundary-validation criteria

Frozen before any provider requests, 2026-10-15. Brian accepts the representation/boundary design and authorizes this small panel only. The question is whether its request boundaries preserve the closed G2/G3 semantics without the V2 integrity failures. G1, the ranker, discovery-readiness, broader collection and projection are outside this experiment.

## Fixed panel

Twenty-one development-source cases, 33 maximum paid attempts: nine single-pair G2 requests and twelve G3 cases with separate act/source and relevance/binding requests. Use only the accepted `represent` and `request_shapes` helpers, unchanged question factories, `jev-1.13.0`, and the original selected-option probability >= .80 gate. No target/context adjustment after seeing answers, threshold changes, label normalization, V2-answer reuse or automatic retries.

The panel includes same-sentence G2 reading/gloss cases (R021/R023), the ambiguous-anchor safe-withholding control R005, five/six-node G2 (R003/R004/R008), nonbiblical attribution (R080/R043), the prepared R058 doubts-anchor repair, long-range G3 (R038/R092/R103/R053), narration-only R078, generic R018/R057, reported R073/R077/R111/R114, and the R076 prayer control. All come from the same six frozen sources. These manually selected source geometries are not evidence of automatic retrieval. R005's interpretive anchor and R038's autobiographical-to-imagined perspective are scope-sensitive diagnostics, not guaranteed easy positives.

Pending forward controls from `collector-v3/check-design-v3.json` are frozen for this panel: R021 reading and R080/R043 nonbiblical anchors are not automatically Bible explanation, R058 uses the explicitly proposed doubts-question endpoint, R078 checks all seven acts, and R111 allows the imagined-recipient reading. V2 references/results remain unchanged. R092 additionally checks the source-supported binding of the bishop's challenge to the reported convicted-felon recipient. R076 checks reported past prayer, address to God, and absence of person-directed acts. R005 preserves its original unclear-only V2 check in parent lineage while the new boundary scope control allows not_linked or unclear: an interpretive fragment without an established textual anchor must not manufacture an explanation. It tests safe non-evidence rather than forcing a particular uncertainty token. These additional checks exercise existing contract meanings, not new constructs.

## Required source audit

Codex must inspect every positive and every failure in any field, including fields without a prepared expectation, against the exact request state AND the full frozen source. Inspect all 21 cases, both G3 phases, raw distributions, source and recipient identity, adoption, conditions, target/utterance/circumstance coordinates, and original source attribution. Classify missing context as a boundary/evidence failure rather than inferring the model had evidence it never received. In particular, the accepted heuristic may omit a reporting introduction from a short exact-utterance request; this risk is intentionally tested, not repaired silently before or after the run.

No successful alias, later phase or export veto can hide a wrong raw observation. Narration-only or nonbiblical-source quarantine does NOT demonstrate semantic success if the underlying answer is wrong. Source-audit flags are not confined to the automatically compared fields. Raw selected choice, selected probability, gated decision and confidence remain separate. Withholding is neither a measured negative nor proof of discrimination.

## Decision rules

**FAIL** if the source audit confirms ANY critical integrity failure: fabricated act/relation/opposite; neighboring or context-only speech promoted into the candidate; wrong source voice or recipient; Bible credit for an extra-biblical anchor; unsupported adoption/current-listener transfer; incompatible/null circumstance credit; loss of source provenance; cross-utterance or cross-state reuse; binding-phase insertion/strengthening of an act. This applies even if the export guard quarantines the record. Technical corruption, incomplete requests or a missing recovery decision cannot produce PASS.

**PASS, scoped to the prepared boundary panel**, requires zero confirmed critical failures, complete technical/provenance integrity, and source-audited discriminating evidence in every core family:

- A same-sentence G2 positive (R023) and one five/six-node G2 positive (R003/R004/R008), with their directed roles supported. The R021 reading control must not emit a false link.
- At least one supported long-range G3 act (R038/R092/R103/R053). R092 must additionally preserve the historical human recipient and demonstrate its circumstance binding, rather than simply reporting a nearby act.
- At least one supported generic current-listener act (R018/R057), with no invented circumstance, and one supported reported act (R073/R077/R111/R114) without current-listener/adoption transfer.
- R078 must positively discriminate narration: all seven acts `not_observed`, not merely withheld. R080 must discriminate source/scope: `not_linked` plus quoted/reported left voice. R076 must preserve the God addressee and not turn prayer into a person-directed act. Source/stance fields not required for discrimination still receive full source audit and cannot contain a wrong definite claim.

**PARTIAL/HOLD** if there are no confirmed critical failures but conservative omissions, unresolved attribution, weak positive discrimination, measurement errors or incompleteness prevent those requirements. Do not lower the requirements or reopen G1/G2/G3 to obtain PASS. Prepared-check disputes must be documented with exact source evidence; keep the original panel score and any qualified interpretation separately. No post-run retrospective replacement checks.

A PASS permits **preparing a separate discovery-readiness decision**, preserving the sparse-ranker limitations. It does not accept the ranker, activate collection, start another representation redesign, or implement pastor projection/comparison/scoring. Brian records the human decision after Codex's Markdown/JSON source-audit recommendation. All rates, recurrence, corpus economics and total useful-item counts remain unestablished; the 790 non-reference V2 positives remain unaudited.

## Execution and recovery

The cumulative ceiling is 33 attempts, including failed/lost replies, reserving 64,000 input tokens each: 2,112,000 tokens and **$0.088704** list price at the documented $0.042/M input rate, with free output and long context disabled. This is a ceiling, not an actual token estimate. Brian runs the fingerprint-bound `pte` command. Codex does not run or monitor the paid job.

Runtime files belong to the configured application's base directory under `evaluation/evidence-supply-boundary-v3/`, outside the repository. Persist raw bytes before parsing, seal each receipt and charged ledger, lock against concurrent execution, reuse only valid identical-panel receipts, show per-request progress and stop on failures without replacement spending. Any invalid/missing charged receipt needs a separate concrete recovery decision. Reports never automatically authorize another run or activate downstream work.
