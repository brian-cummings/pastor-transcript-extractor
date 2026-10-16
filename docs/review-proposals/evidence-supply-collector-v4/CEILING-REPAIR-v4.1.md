# Collector V4.1 — source-ceiling repair, 2026-10-16

**Ready for Brian's revised provider-free development command.** The initial V4 run stopped at the unchanged source ceiling. It produced no development recall result and made no provider requests. Its input, implementation, synthetic tests and historical review are preserved. The old CLI execution mode is retired with an actionable error; this is a separately fingerprinted successor under the existing repair authorization.

## Cause

V4 proposed four width combinations, each in both directions, at every source sentence boundary. Two same-sentence cuts, two remote gloss hypotheses and two G3 targets made its combined source-derived bound **14N**. Source 1618 has **1,099 sentence nodes**, including 516 nodes of five words or fewer. Its bound was **15,386**, above 12,000. The two smaller sources' bounds were below the ceiling, so the reported G2/G3 source overflow identifies the long source. The actual over-ceiling candidate count was not retained and is not reconstructed here. This is candidate multiplication, not source truncation, model behavior or exhausted paid budget.

The implementation should have checked these cheap structural counts before the first dataset handoff. The successor now checks every source and the aggregate **before materializing candidates**. Checks use the existing canonical source snapshots and source sentence parser only, without references or candidate evaluation.

## Repair

At each gap, keep the narrow (1,1) pair and the maximal available pair (up to 2,2), both directions. The intermediate (1,2)/(2,1) variants are no longer separately materialized where the maximal pair is available. Their exact role ranges are contained geometrically in the maximal pair; narrow pairs remain separately available. Near the source ends, maximal widths use only available sentences. Omitted variants are explicitly disclosed in source-only diagnostics.

This is a fixed source-only factorization policy, not a cutoff at the first 12,000 candidates, reference-specific tuning or a higher ceiling. It retains every source sentence, both pair directions and the existing complete-prefix/suffix/nonlocal paths. **Geometric containment does not establish semantic context equivalence.** Wider endpoints can mix or complicate source voice; removing asymmetric variants may affect usable downstream yield. The comparison remains an upper-bound development diagnostic, and no semantic/admission safety claim is made for those wider endpoints.

G2's bound is now **8N**, and unchanged G3 remains **2N**. G1 nomination/framing is unchanged. Hard limits remain **12,000/source and 20,000 total G2/G3, 200/source G1, 6,000-character frames**, with no silent truncation or weakened semantic gates.

## Read-only size preflight

| Source | Sentence nodes | G2/G3 upper bound | Source ceiling |
|---|---:|---:|---:|
| 1565 | 140 | 1,400 | 12,000 |
| 1450 | 257 | 2,570 | 12,000 |
| 1618 | 1,099 | 10,990 | 12,000 |
| Aggregate | 1,496 | 14,960 | 20,000 |

These are mathematical bounds, not actual candidate counts, recall or audited evidence. G1's separate ceiling and complete-framing checks still apply. The existing source bytes also satisfy the unchanged character limits.

```sh
pte analysis collector-recall-repair --revision v4.1 --check-only
```

The checker verifies original source/reference/authority bindings, new implementation/test pins and these size proofs without candidate generation or dataset evaluation. If another source or aggregate size proof exceeds a limit, the workflow stops before materialization and reports the affected source or aggregate. It does not raise ceilings.

## Validation and handoff

**81 focused tests passed** (24 revised tests, 18 original collector/harness tests, 21 fresh safeguards and 18 CLI contracts). The original synthetic failure-class tests also run against the new collector. New regressions cover dense short-sentence growth, geometric coverage of omitted asymmetric variants in ordinary bounded frames, unchanged hard ceilings, source/aggregate preflight failure and retirement of the old command. The complete-role coverage test does not assert semantic equivalence of different endpoint widths. See the [machine-readable repair review](ceiling-repair-v4.1.json) and [new input](repair-input-v4.1.json).

Brian's revised development command:

```sh
pte analysis collector-recall-repair --revision v4.1 --run-development --approve-input 8a619033a9319d224d642fc475f1cbd67986919c74d5c0388662ae787a64e54e
```

Runtime outputs use a new directory, leaving the failed packet's namespace intact:

`evaluation/collector-recall-repair-v4.1/8a619033a9319d224d642fc475f1cbd67986919c74d5c0388662ae787a64e54e/results-v4.1.json` and `.md`, plus the separate natural inventory. They remain under the configured application base directory. The run compares the same frozen references and reports every recovery, regression and remaining miss, candidate counts/growth, deferrals and control contacts. It makes zero provider requests. Brian runs the dataset command per AGENTS.md; Codex ran only synthetic tests and read-only structural checks.

No development result is claimed yet. Codex will interpret the result before preparing new confirmation sources. Fresh V1 remains accepted FAIL / G1 HOLD and retired from confirmation. Closed V4/A1 semantic/admission behavior, questions, thresholds, provenance requirements and typed export/consumer safeguards remain unchanged. Provider calls, collection, automatic attestation, the 790-item V2 audit and pastor projection/scoring remain held.
