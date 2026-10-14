# G1 V2: one focused local-proposition refinement

Status: **PASS — bounded G1 feasibility accepted and closed by Brian, 2026-10-14.**
The [human stage gate](../../../evaluation/g1-binding/feasibility-stage-gate-v2.md)
and [JSON decision](../../../evaluation/g1-binding/feasibility-stage-gate-v2.json)
supersede preparation/pending-review status. V2 raw results and frozen expectations
remain unchanged (198/209 exact checks; 11 accepted bounded residual checks).

Accepted scope: passage-level proposition/object binding, relation/polarity,
voice/adoption, conditions/scope, expressed uncertainty and conservative withholding.
Direct voice and public attitude versus prescription are resolved; simple negation
is sufficiently resolved. A08 preserves reported content, rejection evidence and
unresolved binding without manufacturing an adopted opposite. Other disclosed
binding/adoption limitations and regressions remain visible. No field-filling tuning.

**No V3 or additional provider requests for this gate.** Broader collection, recall,
calibration, denominators/economics, pastor projection/comparison, contradiction/
coherence, clustering, recurrence/rates, G4 and scoring remain held. No automatic next
step is authorized. The CLI blocks further provider execution for this closed gate.
Provider-free record: `pte analysis g1-feasibility-review --stage-gate`.

The remaining proposal and execution-recovery text is historical provenance;
its commands are not current authorization. Follow the stage gate and current handoff.

## Historical G1 V2 execution recovery proposal — 2026-10-14

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

The [execution diagnosis](../../../evaluation/g1-binding/feasibility-v2.execution-recovery.md)
and [JSON snapshot](../../../evaluation/g1-binding/feasibility-v2.execution-recovery.json)
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

Provider-free packet check (does not authorize a replacement):

```sh
pte analysis g1-feasibility-review --revision v2 --check-only
```

## Frozen basis and prepared artifacts

- [V1 results](../../../evaluation/g1-binding/feasibility-v1.results.json) and [readable V1 results](../../../evaluation/g1-binding/feasibility-v1.results.md) are preserved unchanged. V1 made 37 requests, with 138,249 recorded input tokens and 26,573 output tokens. That is request accounting, not a request-economics study.
- [V1 source review](audit-v1.md), with [machine-readable audit](audit-v1.json): all 39 unmet checks are retained; 37 concern the four revised questions and two concern unchanged subject binding. V1 matched 170 of 209 prepared checks. This is not a calibrated accuracy estimate or a feasibility PASS.
- [V2 fixed inputs](input-v2.json) contain the same 28 cases, 37 source candidates, source text/context, phrase pools, authored claims and prepared review checks as V1. [Readable reuse summary](input-v2.md).
- [Exact V2 questions](questions-v2.json) publish only the four changed question contracts. The other questions retain their original meaning and provenance.

Baseline file hashes, content fingerprints, state/candidate identity, raw answer schemas, resolved model, request IDs and request ledger are checked before any reuse or provider construction. The completed V1 result contains the original cached answers and request provenance; V2 reuses that immutable snapshot without requiring a new V1 provider run or depending on untracked cache files.

## Precisely what changes

| Question | V1 failure pattern | Focused V2 clarification |
| --- | --- | --- |
| `relation` | Negated loss predicates split into `loss_possible` versus `retention`; support for a proposal containing “require” splits into support versus prescription. | Identify the underlying predicate independently of polarity, open issue and source stance. `cannot be lost` stays `loss_possible`; retention requires expressed remaining/retaining. The main attitude predicate “supports/opposes requiring …” differs from prescribing that the city should require it. |
| `polarity` | Declarative negations can be scored as affirmed; “oppose” can be treated as denied because it is a negative attitude. | Distinguish propositional negation from attitude valence. “Oppose” affirms opposition; “do not oppose” denies opposition and never implies support. A rejected quoted denial retains its voiced denial. |
| `voice` | Direct unquoted assertions often withhold preacher origin unless the source explicitly says “I teach”; a reporting wrapper can be confused with mixed proposition voice. | Current unquoted/unattributed sermon assertions can be direct preacher speech without an “I believe” marker. Explicit reports, quotations, historical dialogue and ambiguous references override that convention. Judge proposition origin rather than the narrator's reporting wrapper. |
| `adoption` | Direct/negative assertions and explicit rejection remain withheld despite adequate framing. | A direct assertion can be affirmative, negative or qualified. Explicit rejection remains rejection, with original voice/polarity; it never synthesizes an adopted opposite. Bare questions and open issues still withhold an asserted answer. |

Adoption is included because these clarifications affect whether the **same expressed proposition** is asserted, reported or rejected; it is not permission to infer beliefs. New questions are independent and cannot read the other answers. No new speaker/stance defaults are set in code. Listener advocacy is explicitly excluded from attitude/prescription inference unless a distinct in-scope proposition is actually expressed.

The revised questions run across all existing candidates, including the unchanged negative/report/context controls, to expose regressions. The requested negation group is A03/A07/A08/P10/B04; direct-voice group is A01/A02/A10; public-attitude group is P01/P02/P03/P05/P06/P10/B05. No question uses case IDs or expected labels to choose an answer.

## Reuse, request ceiling and unchanged gaps

| Item | V2 |
| --- | --- |
| Cases / candidates | Same 28 / 37 |
| Existing prepared checks | Same 209 |
| Questions recomputed | 148: four fields × 37 candidates |
| V1 raw answers reused exactly | 338 |
| Cumulative V2 provider ceiling | Frozen packet: 37 attempted requests; proposed explicit lost-response replacement: 38 |
| Model / SDK retries / timeout | `jev-1.13.0` / 0 / 45 seconds |
| Withholding policy | Unchanged selected-answer probability ≥0.80; otherwise `unclear` |
| Production / pastor projection | None |

Subject/object identity, selected object/framing/evidence spans, conditions, scope, boundary and epistemic questions are **unchanged**. V1 answers for these remain unchanged even when a different value might complete a record. In particular, A09/P09 subject-binding misses remain visible as conservative **misses**, not retroactively legitimate source ambiguity. P07's unresolved antecedent is a legitimate withholding. Open issues and unanswered questions continue to withhold an asserted answer. Known acts/propositions and their partial fields remain available independently of a stronger composite flag.

The same V1 composition rules retain local partial facts, unknown scope and rejected claims. Their conservative composite gating is not broadened merely to fill more records. Natural controls remain the same three proof-vocabulary negatives; natural-positive reliability and corpus coverage remain unestablished.

Outputs after Brian runs:

```text
evaluation/g1-binding/feasibility-v2.results.json
evaluation/g1-binding/feasibility-v2.results.md
evaluation/g1-binding/cache-v2/request-ledger.json
evaluation/g1-binding/cache-v2/<identity-hash>.json
```

V2 uses a separate cache/ledger and never writes V1 input/results/caches. Reused fields retain V1 question/state/model/request identity; changed fields record V2 question identity and request/cache origin. The ledger records attempts before calling. Returned raw response receipts, model and token usage are persisted before validation; valid receipts can recover locally without new inference. Incomplete or wrong-model responses consume budget without valid cache credit. Cache replay sends no new requests. Do not delete/reset a ledger or bypass the ceiling to finish a failed run; ask Codex to interpret the concrete failure.

## V2 report and close decision

The report repeats the unchanged checks with V1/V2 outcomes, per-field distributions and source records. It separates:

1. **Corrected semantic checks:** previously unmet focused checks now matching; these remain pending source confirmation rather than an automatic semantic PASS.
2. **Legitimate withholding:** source-justified unresolved antecedents, questions/open issues and ambiguous attribution. A missed positive or a raw argmax below threshold is not silently relabeled a match.
3. **Remaining focused failures and regressions:** all unmet checks plus the requested case families, so a recurring negation/voice/attitude problem cannot disappear behind the overall match count. Unchanged binding misses are labeled separately. Codex determines systematicity from the exact sources and raw answers.
4. **Expectations requiring review:** no revision is currently proposed. If post-run source review finds a disputed expectation, record its rationale separately; do not rewrite the original oracle or turn V1 misses into matches.

Codex must inspect every positive/partial observation, changed predicate/voice/adoption decision and the report/negation/negative controls. Simple negation must preserve subject/predicate identity; reported rejection must not invent an opposite; support/opposition must not become prescription or listener advocacy; clear direct discourse must be distinguishable from actual attribution ambiguity. Two differing scopes remain two local observations without a contradiction/coherence judgment.

A confident false in-scope predicate binding or attribution transfer remains a semantic failure even if another reused gate happens to withhold the composite record. Conversely, speculative answers whose in-scope premise is absent must not be counted as asserted pastor observations merely to inflate a failure or success count.

The decision answers **only whether G1 local proposition observations are sufficiently reliable to close bounded feasibility**. A PASS may retain explicitly reviewed conservative limitations; unresolved recurring semantic/contract failures prevent unqualified closure. If the focused core is still systematically unreliable, report that result and stop for Brian's decision. **No V3, general theology-extraction program, automatic acceptance, broader collection or new validation workstream is authorized.**

Still held: G1 expansion/full collection, pastor projection/comparison, clustering, G4, contradiction/coherence judgments, candidate recall, production calibration, opportunity denominators, request-economics studies, rate/recurrence estimation and all quality/exceptional-pastor scoring. G2/G3 and the accepted bounded consumer remain closed.

## Verification and continuation

Thirteen focused V2 tests pass (including rounding boundaries, raw failure retention, receipt recovery and the explicitly bounded replacement): unchanged-state/expectation identity, four-question scope, exact reused answers/provenance, separate cache replay, source/model/answer rejection, cumulative budget enforcement, no invented opposite, retained uncertainty/context decisions and native CLI revision dispatch. These are mock/provider-free checks, not V2 model results. The [TypeSafe plan](../../TYPESAFE_TOPIC_ANALYSIS_PLAN.md) and the top of [HANDOFF.md](../../HANDOFF.md) identify this as the current continuation point.

Question refinements follow the official [TypeSafe Choice guidance](https://docs.typesafe.ai/primitives/choice), [state guidance](https://docs.typesafe.ai/concepts/state) and [Python usage guide](https://docs.typesafe.ai/sdk/python/usage): independent typed questions over the same source state, with code-owned composition and explicit uncertainty. No SDK/transport migration is part of V2.
