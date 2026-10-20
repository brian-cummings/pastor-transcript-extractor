# Current analysis plan and historical review navigation

**Active plans, 2026-10-19:** [product: readable pastor assessment → dimensions → linked evidence](../PASTOR_PROFILE_PRODUCT_PLAN.md) and [implementation: code, milestones and acceptance](../PASTOR_PROFILE_IMPLEMENTATION_PLAN.md). They reference each other and replace the stale implementation roadmaps. Four analytical families organize the detail: preaching style, theological emphasis, theological orientation and pastoral/rhetorical orientation. Segment evidence comes first; optional Ollama illustrative quotes remain last.

That inventory is now [complete with an actual sample](segment-cache-inventory-v1/REVIEW.md): reviewed profile 318, three sermons, 158 eligible topic/treatment blocks and 33 routed salvation blocks. The [first read-only interactive view](segment-profile-view-v1/REVIEW.md) is now built and browser-checked, with unknown fields exposed. The next implementation proposal is **milestones 1–3 together**: descriptive record/rules, worked example, readable screen, claim links, explicit unknowns and the consequential gap/code map. The sample draft belongs inside implementation, not another standalone pre-coding gate. Benchmark percentages and undefined High/Moderate/Low labels remain unpopulated. Do not start another target/quote extractor as a prerequisite. Topic attention is not automatically an adopted position, and historical measurement/containment decisions retain their original scope. No new provider run, collection, profile inference/scoring, or quote implementation is authorized by this planning update.

The tail-end quote must contain substantive content from the strongest CENTER minute. BEFORE and AFTER may contribute only necessary continuation, qualifications or attribution. Use full eligible adjacent segments with actual IDs/time bounds, verify a contiguous verbatim source excerpt, and withhold rather than invent, silently join or borrow an unrelated neighboring quote.

| Material | Current status |
|---|---|
| `segment-profile-view-v1` | Current read-only interactive three-sermon view, source disclosures and timestamp links; zero model calls/writes. |
| `segment-cache-inventory-v1` | Current completed provider-free inventory and concrete three-sermon sample; no model calls or database writes. |
| `pastor-profile-implementation-plan-v1` / the two current plan documents | **Active product/implementation/retirement registry.** Read-only check: `pte analysis structure-readiness --segment-plan --json`. |
| `pastor-profile-product-plan-v2` | Preserved prior product-only planning snapshot; current roadmap implements the worked example with the feature. |
| `segment-evidence-plan-v1` / `docs/SEGMENT_EVIDENCE_PLAN.md` | Supporting preserved segment-first processing and quote contract; current product hierarchy/next step lives in V2. |
| Existing topic, treatment/source/directive/salvation plans and code | Reuse established, compatible observations within their actual meanings; no duplicate inference merely for quotations. Older topic plan remains historical contract/implementation detail. |
| `minute-membership-reconciliation-v1` | Retain fixture-only canonical membership/context findings. It does not authorize production membership or prove collection recall. |
| `minute-evidence-handoff-v1`, `minute-evidence-handoff-implementation-v1`, `evidence-pipeline-trace-v1` | Retain mapping/context/lineage findings. Their exact-span-nomination-first product sequence is superseded. |
| `typesafe-selected-window-bridge-v1` | **Closed dead end:** upstream position nomination is not the default product prerequisite. No inference or new preparation proposed. |
| `typesafe-position-selection-v1` and source audit | **Closed completed dead end:** 30 requests, $0.033297516, one supported nomination, seven invalid geometries and eight withheld outcomes. No more execution/replay/tuning. The old paid CLI command now explicitly refuses before a provider client opens. |
| `existing-source-unit-span-readiness-v1` | **Closed dead end:** whole source units do not express required atomic geometries. This does not imply minute blocks are too coarse for topical analysis. No finer-boundary follow-up is the current next step. |
| `context-extraction-probe-v1` | **Closed, SUPERSEDED_UNEXECUTED:** disconnected OpenAI probe, zero requests. No silent Ollama substitution. |
| `context-evidence-architecture-v1` | Superseded as an upstream product requirement; retain historical proposal and contracts. |
| `collector-retrieval-design-v1`, `collector-retrieval-implementation-v1`, `collector-retrieval-repair-v1.1` | **Closed failed development branch**, not an active roadmap or model experiment. |
| Fresh discovery V1/V2/V3 | Preserve scoped failures, retired-source status, G1 discovery HOLD and remaining uncertainty. Quote deferral does not turn failures into PASS. |
| Source-unit Repair V1 | Retain source-processing support and bounded development result; no production-readiness claim. |
| Original G1/G2/G3/V4/A1/consumer decisions | Retain original scopes. G1 passage feasibility PASS/closed differs from G1 discovery HOLD. V4 raw FAIL/containment HOLD and bounded A1 PASS stand. No automatic authority for a new segment-level theological claim. |

Frozen source, reference, receipt, acceptance and hash-pinned proposal files are preserved. `STATUS.md` sidecars and [the current registry](pastor-profile-implementation-plan-v1/plan-v3.json) supersede their active recommendations, not their historical evidence. Do not follow an old AUTHORIZED command as a new execution instruction. No cache/model deletion or broad refactor occurred.
