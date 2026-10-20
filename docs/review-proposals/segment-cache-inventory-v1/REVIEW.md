# Cached segment evidence: first bounded profile slice

**Existing observations are sufficient to start a read-only segment-backed profile view without another model experiment.** The inventory selected reviewed profile **318** on cached coverage, not on positive answers. It contains three eligible recordings, **158 topic blocks**, compatible four-dimension treatment answers for those same 158 blocks, and **33 routed salvation blocks** with the frozen nine-leaf observation policy.

[Read the actual sample with full supporting segments](/Users/briancummings/Documents/PastorSearchData/evaluation/segment-cache-inventory-v1/2fdec9947ae2ca5a11ab17094fb159e982365693dc5d10549d276e0cb6995559/sample-v1.md).

[Complete inventory, provenance, coverage and gaps](/Users/briancummings/Documents/PastorSearchData/evaluation/segment-cache-inventory-v1/2fdec9947ae2ca5a11ab17094fb159e982365693dc5d10549d276e0cb6995559/inventory-v1.json).

The source titles name John Bradshaw, but the reviewed database profile has no display label. This report preserves profile 318 and its reviewed membership rather than promoting title text into accepted identity. Its current effective membership is exactly videos **4589, 281 and 3973**. This is a bounded available sample, not a representative sample of a whole ministry.

| Recording metadata | Existing topical-attention signal |
|---|---|
| *The Shaking* (3973) | God's character/action; ethics; spiritual formation; sin/human need |
| *The American Experiment: Success or Failure?* (281) | Society/public life; ethics; sin/human need; God's character/action |
| *Demons & Dry Places* (4589) | Spiritual formation; God's character/action; spiritual conflict; ethics |

These summaries describe attention in the three supplied sermons, not a newly measured doctrinal position, score, recurrence claim or comparison. The sample links existing representative segments with full target text, exact block/segment/time provenance and the original topic scores. It includes cached treatment probabilities and routed salvation observations without adding measurements or extracting display quotes.

## What was reused

The read-only metadata selection was bounded to the latest 12 persisted version-1 topic runs, one per video. All 12 current source artifacts passed the existing accepted-sermon/effective-reviewed-membership gate and current topic/model compatibility checks. The sample selection maximized eligible cached topic blocks, then sermon count, then lower profile ID, independently of topic scores or salvation positives. It selects 318's 158 blocks rather than choosing a flattering topic or manufacturing a sampling threshold.

The checks retain exact Jev 1.13.0, question-pack version/digest, current target block/time/segment identity, existing topic eligibility rules and frozen salvation routing/thresholds. Treatment targets must match topic targets; salvation also checks exact context target text. Wrong model/question/target identities remain unavailable. Unrouted salvation blocks remain unmeasured; three unresolved leaves remain excluded, and below-threshold values do not establish negative positions.

**Nine of the twelve database topic materializations are stale relative to current source-artifact fingerprints.** They were not reused. The current artifacts already contain compatible cached sermon projections and raw observations, so the inventory read those directly. It did not regenerate projections, alter source artifacts, write a database analysis run, refresh the corpus or call a model. Two of the selected profile's materializations are current; the older 4589 materialization is stale and was bypassed. The changed whole-artifact fingerprint is not itself proof that every topic value changed; the report preserves the distinction.

## Gaps that remain

- Production listener-directive, public-life-treatment and source-material observations are absent from these 12 classification artifacts. Their bounded question validation elsewhere does not fill those fields in this sample. A supplemental read-only check of **474 exact full-pack paths** (158 selected blocks × three current approved packs) found **zero matches**, using current context/model/question/diagnostic identity. This was not an exhaustive scan of legacy review outputs, leaf-by-leaf compositions, other models or the corpus. Any later enrichment should check those narrower reuse possibilities before requesting inference.
- The existing broad topic layer cannot resolve every theological stance, adoption, object or polarity. Do not display a topic as an affirmed belief. The nine salvation leaves retain their defined local meanings; the three unresolved relationships remain unknown.
- Raw cache compatibility is not a new semantic source audit of all observations. These recordings were already development/review material, not fresh confirmation. Three sermons and overlapping minute blocks establish no independent recurrence, period/series stability or comprehensive pastor picture.
- Video 281 includes targets longer than a nominal minute. Preserve the actual block bounds; do not pretend earlier pipelines guaranteed exact 60-second cuts. Future quote context uses actual adjacent blocks.
- The optional Ollama illustration stage remains unimplemented and unexecuted. Full target segments in this sample are evidence links, not polished quotations or an exact-span requirement. When implemented later, its CENTER/BEFORE/AFTER contract remains the active plan.

## Recommendation and verification

Proceed with the first **read-only profile presentation of these existing segment-backed observations**, showing per-sermon/topic/treatment evidence and unsupported fields explicitly. This inventory has produced a concrete sample rather than another abstract gate. Do not require completing all enrichments or obtaining exact quotations before reviewing that view. Any new position inference, recurrence/comparison/scoring, broader collection or missing semantic measurements remains a separate scope decision.

**28 focused tests passed**: model/question identity, target mismatch, missing route coverage, unresolved leaves, unmeasured-versus-negative states, selection independent of positives, read-only CLI and existing command contracts. No provider requests, model loads, database writes, new profile aggregation, collection, source changes or quotation extraction occurred.

```bash
pte analysis structure-readiness --segment-inventory --check-only --json
```

The same command without `--check-only` recreates only the provider-free inventory/sample under the configured application base directory. It cannot infer or write to the database.
