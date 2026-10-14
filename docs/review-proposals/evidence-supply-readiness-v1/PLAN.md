# Evidence-supply / collection-readiness gate V1 plan

Status: **planning only — gate implementation and execution unauthorized**.
Prepared 2026-10-14 at Brian's request. Broader collection and downstream
projection/scoring remain unauthorized. [Machine-readable plan](plan-v1.json).

## Decision and recommendation

The next question is whether a specified collection workflow can supply useful,
grounded, compatible evidence for named desired characteristics at an explicit
cost, with omissions and unknowns exposed. It is separate from construct
feasibility and the supplied-evidence consumer acceptance. A PASS would support
preparing a bounded collection activation proposal; it would not activate collection.

Recommend authorizing **provider-free readiness-packet implementation and
preparation only** as the next bounded step. It would inventory existing evidence,
prepare source adapters and fixed review cases, and produce a concrete validation
and cost proposal. Paid validation requires a later explicit decision on that
prepared packet. No gate implementation or dataset inspection is performed by this
planning change.

## Authoritative starting point

- [Current handoff](../../HANDOFF.md): G1 V2 PASS and closed, with 11 residual
  checks preserved; no V3 or further provider requests authorized.
- [G2 decision](../../../evaluation/g2-binding/feasibility-stage-gate-v2.md):
  bounded PASS with qualification/rationale and stance limitations.
- [G3 decision](../../../evaluation/g3-address/feasibility-stage-gate-v2.md):
  bounded PASS with conservative positive/context-binding limitations.
- [Consumer decision](../../../evaluation/observed-profile-consumer-v1/acceptance-decision-v1.json):
  accepted and closed, including A12/C05 and A15/C10 deviations; 15/17 exact
  matches and 17 invariant passes remain unchanged.
- [Desired-profile gap analysis](../../PASTOR_PROFILE_GAP_ANALYSIS.md),
  [architecture](../../PASTOR_PROFILE_EVIDENCE_ARCHITECTURE.md),
  [59-leaf registry](../pastor-contracts-v1/REGISTRY.md),
  [shared contract](../profile-evidence-v1/CONTRACT.md),
  [field catalog](../profile-evidence-v1/FIELD_CATALOG.md) and
  [estimands](../profile-evidence-v1/ESTIMANDS.md) define the product/evidence bridge.

Older statements that G1 is unimplemented describe historical stages. Its bounded
PASS does not establish natural-positive reliability, production calibration or
full G1 collection. The frozen consumer's G1 examples remain design-only; no
pilot results are inserted into that accepted packet.

The [existing analysis readiness](../../analysis-readiness.md) measures durable
`sermon-basics@4` freshness and aggregate completeness. Its 90% coverage and
three-sermon operational defaults do not establish semantic coverage, opportunity
denominators, recurrence or sufficient evidence for these new fields. Its historical
corpus snapshot is not a current inventory.

## Proposed scope and review axes

All C01–C20 stay visible. First readiness claims are confined to source-linked
local examples (E0); E1–E6 remain inactive. G1 stays within the accepted assurance
and public-policy proof subjects. G2/G3 stay within accepted relation/address
meanings. No new taxonomy, measurement question, threshold or tuning cycle is
proposed. Other positions and full interpretive/development inventories remain gaps.

| Axis | Prepared evidence and acceptance requirement |
| --- | --- |
| Product fit | One row per C01–C20: required observation, existing support, missing semantics, allowed local wording and ceiling. Leaves cannot replace richer positions/development/address. C14/G4 and D01–D06 remain held. |
| Source / eligibility | Exact transcript and target hashes, segment/time locators, reviewed boundaries and effective speaker membership/content decisions with policy/review references. Unknown attribution permits passage inspection only. No identity or extraction edits. |
| Compatibility / transport | Original question/run/model/decision and per-answer reuse provenance; source aliases, target/context roles, independent meanings and missingness survive adapters. Scripture/style reuse needs explicit compatibility review. Incompatible records are withheld rather than recollected automatically. |
| Discovery / supply | Reference opportunities and positive/negative evidence identified from complete fixed sermons independently of automatic candidates. Report omissions, unsupported candidates and truncation by capability. Frozen catalog coverage is not discovery recall. |
| Natural-input judgment | Inspect positive, negative and withheld natural outputs against source and prepared references, including wrong objects, reported/rejected voice, context transfer and legitimate withholding. Preserve errors; no post-result oracle changes or automatic tuning. |
| Units / opportunities | Duplicate/overlapping utterances, recording aliases, episode boundaries, repeated material, dates and series remain separate. Opportunity definitions include negative/unresolved units independently of positive acts. This gate audits prerequisites; it computes no pastor rates or recurrence. |
| Operations / economics | Exact reusable answers, missing judgments, request packing, token assumptions, attempt/token/cost ceilings, zero automatic retries, raw receipts, interruption accounting and failure handling. Bound total spending before constructing a provider. |
| Useful evidence supply | Prepared examples show known observations and unresolved/missing fields together. No profile attribution or stronger claim bypasses source gates; no accepted consumer or pilot artifact is rewritten. |

Readiness is recorded per capability, field, source route and claim level. No
single sample count, average completeness percentage or composite score decides it.
Technical inventory checks can pass while natural validation remains unestablished.

## Work after separate authorization

1. **Prepare a provider-free inventory and contract packet.** Pin accepted decision
   and source artifacts by hash. Inventory existing compatible runs and missing
   adapters read-only; distinguish current/missing/stale/blocked from semantic
   compatibility. Deliver `REVIEW.md`, `input-v1.json`, a C01–C20 readiness matrix,
   source/reuse manifest and proposed checks. Codex owns interpretation and defaults.
2. **Prepare transport checks.** Use copies of frozen source rows plus clearly
   synthetic corruption controls for stale sources, eligibility conflicts, duplicate
   aliases, unknown dates, incompatible semantics, missing target evidence and
   withheld binding. Test lossless evidence transport and explicit withholding.
   Real G1 transport is a new adapter check, not a consumer-acceptance reopening.
3. **Prepare a fixed natural-sermon validation proposal.** Proposed development
   ceiling: six complete, readable sermons across two effectively reviewed profiles,
   with three sermons per profile where available. This is a workload ceiling, not
   a sufficiency or representativeness rule. Codex prepares exact IDs, hashes,
   selection rationale and full-sermon reference opportunities, including local
   negatives and counterexamples; Brian reviews concrete results. Include natural
   positives for each capability being tested and non-candidate passages. If this
   ceiling cannot supply suitable cases, report that capability blocked and propose
   a scope change; do not expand automatically or ask Brian to design the sample.
   No corpus-recall or production-calibration claim follows from six sermons.
4. **Freeze the paid-run proposal before seeking authorization.** Supply exact
   questions/candidates, reuse map, natural reference decisions, per-capability
   criteria, maximum attempts/tokens/cost, missingness/failure rules and a runnable
   `pte` command. Determine budgets from the prepared inputs, not historical pilot
   request counts. Any unpriced or unsupported workflow stays blocked. Existing
   occurrence policies remain frozen where approved; `.70` display cutoffs and
   experimental `.80` choices are not silently promoted into production policies.
5. **Brian executes only a separately authorized bounded run.** Codex does not run
   or monitor provider/dataset validation. After Brian returns results, Codex
   audits all errors/withholdings and source-backed rows, assesses useful supply,
   and recommends a scoped outcome. Preserve raw results and frozen expectations.
6. **Record Brian's decision separately and stop.** Write Markdown/JSON acceptance
   with source/result fingerprints, limitations and continuing holds. Any broader
   collection proposal must specify its own population, route, spending and activation;
   it requires another explicit decision.

## Proposed outcomes and stopping rules

- **PASS for a named scope:** transport/source/eligibility invariants pass, bounded
  natural validation supports the declared local uses under criteria frozen before
  execution, omissions/withholdings are disclosed, and operations fit approved caps.
  Permits recommending a separate collection proposal only.
- **PARTIAL:** some capabilities/routes support local evidence supply while others
  lack semantics, reliable binding, coverage or compatible sources. Name exactly
  what could be proposed for collection and what remains blocked.
- **FAIL:** unsupported attribution, fabricated relations/opposites, lost provenance,
  invalid accounting or systematic unreliable supply prevents the declared use.
- **BLOCKED / UNESTABLISHED:** required source reviews, cases, compatible runs,
  discovery design, decision policy or price evidence are unavailable. Provider-free
  packet-integrity success is never reported as empirical readiness PASS.

Do not repair failure by filling unknowns, changing frozen expectations, restarting
closed pilots or spending beyond ceilings. Revisions require a new concrete proposal.
Production calibration and population recall remain unestablished unless separately
designed and authorized; this bounded gate can identify those blockers, not waive them.

## CLI tie-in and handoff

Existing provider-free checks, runnable now if needed:

```sh
pte analysis g1-feasibility-review --stage-gate
pte analysis profile-evidence-check
pte analysis observed-profile-review --check-only
```

Proposed new entry point, **not implemented and not runnable yet**:

```sh
pte analysis evidence-supply-review --prepare-only
pte analysis evidence-supply-review --check-only
```

`--prepare-only` would build the read-only inventory/packet and require an explicit
source scope; `--check-only` would validate frozen inputs without inference or
database mutations. The exact scope arguments and any execution flag must be
prepared with the authorized implementation. Default behavior must remain
provider-free; paid execution must require a separately fingerprinted authorization
and enforce the fixed manifest/caps. No standalone-script workflow is proposed.

No dataset-validation command is ready in this planning step. Once a bounded
implementation and frozen run proposal are prepared and authorized, give Brian
the exact `pte` command with all inputs/defaults supplied. His role is execution
and approval/rejection, not selection, JSON authoring or experimental design.

Continuing holds: G1 expansion/full capability collection; broader collection;
production calibration, population recall, operational opportunity denominators
and collection-economics studies beyond separately approved scope; pastor
projection/comparison; contradiction/coherence/G4; clustering; recurrence/rates;
quality and exceptional-pastor scoring. G1/G2/G3 and consumer acceptance stay closed.
