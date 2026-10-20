# Paired product and implementation plans

**Completed Brian's requested documentation replacement.** The active pair is:

- [Product plan](../../PASTOR_PROFILE_PRODUCT_PLAN.md): reader experience, analytical meanings and evidence boundaries.
- [Implementation plan](../../PASTOR_PROFILE_IMPLEMENTATION_PLAN.md): existing modules, versioned description contract, evidence-to-wording rules, read-only screen, delivery milestones and acceptance checks.

Both documents reference each other. The next implementation proposal is milestones 1–3 together: a working descriptive profile with its worked sample, traceable claims, explicit unknowns, tests/browser checks and consequential gap/code map. The draft is part of the first feature, not another standalone prerequisite before coding. Missing enrichments are prioritized afterward; optional Ollama quotations and benchmark comparison remain separately held.

Replaced the active stale guidance in `TYPESAFE_TOPIC_ANALYSIS_PLAN.md`, `PASTOR_PROFILE_EVIDENCE_ARCHITECTURE.md` and `analytical-review/IMPLEMENTATION-PLAN.md` with clear links to the current pair. The old mixed topic/implementation document's accepted contracts and records are preserved in a same-directory historical copy; its referenced downstream-contract and G1 anchors point to that copy. The prior product document is also preserved exactly because the V2 review pins its earlier hash. The [sealed archive manifest](archive-manifest-v1.json) records every original/archive path and matching hash. Frozen review/measurement JSON, raw receipts and source evidence were not changed.

Updated root navigation, old-plan status sidecars, progress notes and the current registry. The current CLI verifies both active document hashes, their reciprocal references and all historical archive hashes:

```bash
pte analysis structure-readiness --segment-plan --json
```

**21 focused tests passed** for the planning/retirement policy and existing CLI contracts. The actual CLI check passed. No model loading/calls, database writes, fixture/corpus jobs, implemented profile rules, quotation execution, collection, production activation or new scoring/comparison occurred. The proposed `--description` option is documented as not yet implemented.
