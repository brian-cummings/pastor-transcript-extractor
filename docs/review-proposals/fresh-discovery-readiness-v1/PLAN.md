# Fresh-source discovery/readiness evaluation proposal — 2026-10-15

**Recommended next decision: authorize bounded provider-free preparation on three fresh sermons.** Freeze the source-only baseline and candidate/envelope inventory, then independently inventory source opportunities and prepare an exact semantic preflight. No provider requests or natural-source evaluation have been executed. The [plan JSON](plan-v1.json) is a proposal, not execution authority.

Brian has [accepted bounded A1 containment PASS and closed that development panel](../g3-atomic-admission-v1/acceptance-decision-a1.md). Preserve V4 raw FAIL / containment HOLD. Do not reopen interpretation/admission research or replay the 24 cases. This evaluation asks whether natural discovery supplies the evidence those accepted contracts need, and how much review it costs to make that evidence usable.

## Proposed fresh sources

| Role | Video ID / channel source ID | Recording title | Existing extracted sermon interval |
|---|---|---|---|
| Primary | 1565 / 66 | Stockbridge Grace Tabernacle SDA Church - Noon Power Hour | 938.870–2479.119 seconds |
| Primary | 1450 / 60 | What Really Happened at the Fall? | 1786.950–3826.240 seconds |
| Primary | 1618 / 32 | “Going Forth Conquering” by Andre Miller | 0–3982.400 seconds |
| Technical reserve only | 4069 / 48 | Keith Parris “Blessed Assurance” | 43.070–819.200 seconds |

Titles are inventory labels; they do not establish speaker identity or pastor ownership. Existing extraction metadata marks these as accepted sermons without guest flags. That is eligibility metadata, not a new source audit. Whole recordings and raw transcripts remain available to check reporting continuity, extraction omissions and actual sermon bounds before freezing normalized main-source coordinates.

The [manifest](source-manifest-v1.json) pins local transcript and extraction files, IDs, hashes, intervals, selection order and exclusions. From 713 metadata-eligible records, order by SHA256(`fresh-discovery-readiness-v1:` + YouTube ID), retain distinct source channels with available local artifacts and accepted-sermon/no-guest metadata; omit Bible-study/Bible Answers Live/Q&A titles. Exclude **all sources from development channels 33/44**, not merely videos 350/421/1046/1200/4050/4430. Do not inspect candidate quality or reference opportunities to choose recordings.

No existing `sermon_analysis_runs` or explicit source/video/YouTube references in the prior review/test files were found for these selected recordings. This is project-evaluation freshness, not model-training novelty or a guarantee that no person previously watched a recording. They are not a representative corpus sample. Validate byte-identical/normalized duplicate recordings against the development sources during preparation; a duplicate or unusable recording is a technical exclusion, documented before reference discovery. Use the reserve only for missing/corrupt/non-sermon/duplicate evidence or irrecoverable extraction failure. Sparse opportunities or poor retrieval are **not** reasons to swap a valid sermon. Any further replacement needs a versioned selection record, not quiet substitution.

## Freeze discovery before knowing the answer

1. Validate source identity, language/readability, extraction boundaries and caption normalization using existing artifacts. Preserve the full recording transcript plus the reviewed main-sermon span. Do not rerun classifiers/providers, strip difficult speech or cut a sermon to fit a budget.
2. Pin the existing Collector V3 source-only geometry/search policy and V2 G1 retrieval policy. Materialize natural candidate IDs, exact endpoints, retrieval ordering, all automatic envelopes and explicit deferrals **before authoring references**. Keep old lexical vocabularies/ranker unchanged, including their known weaknesses. The source-derived candidate bound and ceiling failures are reported, never silently truncated.
3. Seal that inventory and a source-only semantic sampling queue. Then Codex reads each complete normalized sermon independently of candidate output and inventories every definite compatible opportunity, ambiguous/negative opportunity, required roles, reporting identity, recipient, source stance and qualifiers. Use a coverage ledger for every source segment; do not stop after enough positives. This is procedural separation with immutable artifacts, not a claim of independent annotators or inter-rater reliability.
4. Match that source-derived inventory against the sealed natural candidates/envelopes. An auditor-supplied exact span or manual envelope repair is a **rescue diagnostic**, never a natural-discovery success. Store original and repaired states separately. Do not revise gold expectations, ranking, windows or budgets after outcomes are visible.
5. Prepare the exact request states and provider budget only after those counts are known. Brian receives a fingerprint-bound `pte` command for any authorized dataset execution. A paid semantic step requires separate concrete authorization; the current CLI only verifies this proposal.

The prototype currently has fixed-panel V4/A1 constructors: a fresh source cannot pass by substituting a new fingerprint into that packet. Preparation therefore includes a small versioned fresh-packet validator/adapter and source-only envelope materializer, preserving the existing measurement questions, thresholds, typed identity checks, phase isolation and admission invariants. Prove these with focused synthetic tests. Do not edit the old pinned validators or reopen the closed panel. If the mechanical adapter cannot retain the safeguards, report the integration blocker before inference; do not bypass admission to produce a profile.

## Scope and denominators

Test **G2 Bible explanation** and **G3 atomic current/reported acts** with the accepted question factories and admission requirements. Record circumstance geometry/relevance/binding diagnostically; this proposal does not authorize exporting a circumstance claim. Add the existing **G1 assurance/pardon frames only** as a separately reported route. Those frames do not cover general theological propositions. Public-policy/city-ramp examples or unrelated propositions cannot substitute for a missing natural assurance opportunity. This pilot cannot establish broad G1 theological-position collection readiness.

For each route/source, report distinct stages:

- **Available opportunity:** a source-audited definite opportunity within the declared semantic scope, with exact necessary roles and provenance. Ambiguous/incompatible/no-opportunity instances are separate denominators, not positives or discovery misses. Extraction omissions remain source-availability failures.
- **Natural discovery recall:** unique compatible reference opportunities covered by an automatically generated candidate / all definite compatible available opportunities. A hit must contain each complete required role and preserve the exact semantic target/qualifiers; a citation, keyword or overlapping text alone is insufficient. Freeze matching rules before scoring. Also report strict exact-endpoint matches separately to expose geometric variation.
- **Automatic supply sufficiency:** discovered opportunities whose *original automatically generated envelope* includes the source/recipient/continuation evidence needed for that exact claim. An independent source review judges this; the envelope builder does not attest its own semantics. Incomplete envelopes stay deferred. Report natural discovery-to-sufficient-envelope loss and total sufficient-envelope recall separately.
- **Measured and admitted yield:** only for the frozen provider sample, separate raw positives, withholding, unsupported fields, provenance incompatibility, quarantine and audited admitted local evidence. Do not multiply sampled semantic precision by full candidate counts to invent usable corpus totals.
- **Review burden:** active review minutes and item counts for independent reference construction, candidate/source review, envelope repairs, claim-witness preparation and output audit separately. Report median/p90, unresolved deferral fraction, source-specific failures and audit-complete counts. Codex active review time is not validated human-annotator throughput. Unknown timing remains unknown.

A local A1 witness remains source-controlled. This test measures whether automatic envelopes make reviews straightforward, **not whether automatic attestation has been established**. It cannot authorize reviewer-free collection. Every semantic positive, prepared mismatch, withholding, incompatible provenance condition and admitted field in the sampled run must be audited; no V2-style unaudited-positive tail may be called usable.

## Bounded experiment and precommitted targets

Use three primary full sermons; at most 150,000 canonical characters per source / 300,000 total. Preserve the V3 12,000 G2/G3 candidates per source and 20,000 aggregate ceilings, and a proposed 200 G1 candidates per source cap. Any overflow produces HOLD before inference; no source or candidate truncation. The reserve is not an additional fourth evaluated sermon.

If a later semantic step is approved, sample at most **120 natural candidate units**, 40 per source: G1 10, G2 15, G3 15, in frozen source-only baseline order with stable hashes for ties. Leave unused quotas unused; do not fill from known positive references. Request ceiling **240**, zero automatic retries; exact input-token/list-price reservations remain pending request materialization and current technical preflight. No paid command or spending authority is supplied now. Sample coverage and full-inventory recall remain separate results.

Proposed practical pilot targets, frozen before evaluation:

| Requirement | Proposed decision rule |
|---|---|
| Integrity | Any unsupported/unresolved admitted item: FAIL. Zero silent truncation, reference injection or identity/provenance bypass. |
| Opportunity coverage | Complete source-reference census; at least 5 G1-assurance, 10 G2-explanation, 5 G3-current and 3 G3-reported definite opportunities across the panel. Insufficient/absent opportunities: HOLD for that route, never replacement or invented positives. |
| Natural recall | At least .80 per route aggregate and per source/route with a nonzero denominator. Report exact numerators/denominators and ambiguity counts; these are feasibility targets, not population accuracy guarantees. |
| Automatic envelopes | At least .80 total sufficient-envelope recall per route; no manual repairs counted as automatic sufficiency. |
| Review burden | At most .20 require manual envelope repair; at most .20 unresolved review deferrals; median active candidate-review time at most 5 minutes. Report raw distributions and route/source splits. |
| Non-vacuity | Sampled, source-supported G3 evidence must actually reach the current/reported local consumer for any claimed route; missing a claimed family means HOLD, even if full-inventory retrieval looks good. G1/G2 route claims likewise require supported admitted evidence, not only keywords. |

Reference construction plus output review is capped at **480 active minutes**. If coverage/audit remains incomplete, report budget exhaustion and HOLD; never silently drop hard cases. These operational targets are proposed judgments for Brian, not changes to semantic contracts. A positive result recommends a separately scoped small real collection using the routes actually established, with review provisioned. It does not automatically activate collection, certify general G1 positions or authorize projection. A failure is diagnosed as availability, discovery, geometry, envelope, measured withholding/error, admission incompatibility or review-capacity loss; no automatic prompt/ranker redesign follows.

## What is ready now

Source selection, file identities, baseline hashes, measurement/admission acceptance and the proposed design are reviewable now. **Fresh references, natural candidate counts, automatic-envelope results, provider states/budget, reviewed yield and costs do not yet exist.** Source-controlled review and the adapter gap are explicitly preserved. No paid calls, discovery execution/tuning, broader collection, 790-item V2 audit, recurrence/rates or pastor projection/comparison/scoring are authorized.

```sh
pte analysis fresh-discovery-readiness --check-only
```

This read-only command verifies the proposal, accepted A1 closure, selected source identities/hashes and existing metadata only. It does not discover candidates, author reference labels, replay the old panel, infer semantic answers or write runtime artifacts. If Brian approves the bounded preparation above, Codex prepares its versioned inputs/defaults and executable `pte` handoff; Brian is not assigned source selection or annotation work.
