# Minute-block evidence handoff — implementation proposal

**Implement a bounded nomination handoff after the existing localization pipeline. Keep the minute blocks, transcript segmentation and accepted measurement/admission semantics.** Use the project's configured Ollama backend for prospective untrusted nomination; keep Jev for its existing typed measurement role. No new handoff implementation, provider preparation/execution, or model choice is authorized by this proposal.

Brian authorized this proposal and the first cleanup step. That cleanup is complete: the unexecuted OpenAI probe is **SUPERSEDED_UNEXECUTED**, its active CLI prepare/run modes are blocked, and its original packet/authorization remain historical. Supersession is not a semantic FAIL. [probe-supersession-v1.json](probe-supersession-v1.json) records the new decision without rewriting the old one.

## Integration point and retained behavior

Read the persisted accepted extraction after sermon localization. Preserve source/transform identity, retained segment membership, block IDs, timing, cached role/topic packs and original classification decisions. A separate analysis handoff assembles source context and nominates exact G2 pairs or G3 utterances. It must not reclassify the sermon or change what an existing answer means.

The pipeline has five-minute coarse discovery and nominal minute fine blocks. These are navigation/processing units, not guarantees of complete propositions or acts. The trace also found oversized normalized units, historical 90-second Ollama fine blocks and an older TypeSafe builder. The adapter must record the actual builder/normalization lineage; it cannot pretend those artifacts already contain today's minute-level analysis.

There are no persisted topic-analysis blocks or sermon-analysis runs on the three traced sources. Consequently, no existing Jev semantic result can simply be reused as their new exact observation. Elsewhere, reuse requires identical source, model, question/pack, context and routing identity. A broad topic/role score is not a G2 edge, G3 act or provenance witness.

## Context policy: centered on the actual minute anchor

The initial parent-only idea was checked and rejected as insufficient. Today's deterministic coarse boundaries split CE-03's explanation and CE-11's reporting identity. A historical five-minute block containing the evidence does not prove that the corresponding current parent contains it.

Propose one deterministic context per anchor, before model output:

1. Verify the canonical source and transformation lineage. Construct a conservative canonical hull of source units contributing to the center block. **Separately verify the exact center-content mapping.** A broad source-unit hull does not make every included word part of the center.
2. Form a nominal neighborhood from source units overlapping the interval from **120 seconds before the block starts to 120 seconds after it ends**. This is context assembly from existing timestamps, not resegmentation or a semantic retriever. Long indivisible units can make the time interval approximate; preserve that diagnostic.
3. Cap the canonical envelope at **6,000 characters**, preserving the entire anchor hull. If the anchor alone is too large or exact mapping is unresolved, defer. Never truncate the anchor, a nominated act, or a required role to fit.
4. When optional context exceeds the cap, allocate half the remaining character budget to each side, subject to availability; use otherwise unused right-side capacity on the left. Keep one contiguous exact source slice. Trim optional outer edges inward to whitespace where possible; retain their absolute offsets and mark budget/unit-boundary cuts. Context clipping is not a claim of completeness.
5. Do not automatically expand, query another source, or rerun after a nomination reports missing context. Preserve unresolved remote attribution/explanation as a deferral. Relationships beyond the bounded envelope remain a disclosed limitation.

The centered neighborhood and caps are prospective development choices, not measured operating points or new frozen confirmation gates. They must be fingerprinted before any future outputs; this design does not authorize tuning them against the old references.

## Worked source-only arithmetic

These examples use the first listed current anchor from the completed trace. Bounds are canonical codepoint offsets, end-exclusive. They are arithmetic demonstrations before optional whitespace-edge trimming, not materialized requests or semantic recovery.

| Case | Existing anchor | Canonical anchor hull | Proposed context | Characters | What it supplies |
|---|---:|---|---|---:|---|
| CE-03 / source 951 | 48 | [40019, 40788) | [37543, 42752) | 5,209 | Luke/taken-left anchor and later destruction explanation. |
| CE-11 / source 951 | 8 | [6782, 8360) | [4058, 10058) | 6,000 | Earlier Matt identity plus the reported request to Ed. Nominal time neighborhood is 6,871 characters; optional left context is budget-clipped. |
| CE-12 / source 520 | 9 | [7997, 8881) | [5592, 11265) | 5,673 | Paul/letter attribution, virtues antecedent and put-on-love exhortation. |

All reviewed focal/support spans fit these example envelopes. That does not establish exact center mapping, clean semantic targets, general context coverage or discovery recall. These are retired development examples. Source 520's manifest ASR/caption discrepancy remains disclosed; its canonical text derives from the persisted caption extraction and must not be relabeled as ASR.

## Nomination interface

Each request identity contains source/transform hash, center block and source ranges, segment IDs/timing, exact envelope and cut diagnostics, task family, and prospective prompt/schema/model/config identity. A future preparation must resolve and lock the **actual configured Ollama model digest** and context/output/runtime budgets. The project default is currently `gemma3:4b`; the mere presence of `gemma3:12b` is not authority to substitute it. No model comparison, acquisition or health-check generation is part of preparation now.

A nominee contains only:

- A request/context-bound ID and G2 or G3 family.
- Ordered, distinct, exact G2 anchor/explanation spans, or one contiguous P1 G3 utterance.
- Source-backed dependency/provenance/sufficiency hypotheses, explicitly untrusted.
- No-nomination, missing-context, uncertain or saturation status where applicable.

At least one G2 endpoint or the G3 act must intersect **verified center content**. Intersection with optional context or a conservative unit hull is insufficient. If exact center ownership cannot be established, defer; do not invent precision. Evidence may cross block boundaries without changing the underlying blocks.

Literal validation checks exact canonical substrings, offsets, hashes, role shapes and declared dependencies. Semantic/source review still checks omitted qualifications, actual explanatory linkage, reporting identity, addressee and adoption. A valid substring is not proof of those facts. No nominee is LocalEvidence, a Measurement or a source-review witness.

Requests over overlapping anchors can nominate the same event. Deduplicate by source hash, capability and ordered role geometry, retain every originating context, and preserve incompatible voice/recipient hypotheses as a conflict. Assign a deterministic canonical owner after validation; do not use ownership to suppress initial nominations. Identical geometry never licenses merging different reported/current claims into pastor credit.

## Measurement/admission handoff

The data handoff can map exact role/utterance coordinates and the supplied source envelope into prospective measurement transport. It must not assert extractor-generated source labels, recipient or adoption as measured facts. Existing G2/G3 questions, phase isolation, P1/A1 meaning and .80 gates remain unchanged.

There is a real adapter limitation: current V4 validators and A1 authorities bind particular packets/receipts. They are not a generic authorization to interpret/admit these new observations. The implementation proposed here therefore provides a **data-only mapping specification and synthetic contract tests**, not live Jev/admission/consumer activation. A later adapter must explicitly bind new receipts and accepted source/claim authority. No old witness is inherited and no automatic provenance attestation is implied.

Similarly, current center-block questions that allow context only as clarification cannot silently score a cross-block relation from its context. A new nomination stage may select such a complete pair; the unchanged downstream measurement then receives that exact pair as its target under a separately authorized transport.

## Small provider-free implementation scope

Recommend approving only:

1. A canonical source/block mapping interface with reversible references or explicit ambiguity/deferral.
2. The bounded context planner and fixed retired-case materializer described above.
3. An untrusted nominee DTO/validator and immutable request identity; **no provider executor yet**.
4. The data-only prospective measurement mapping specification and synthetic checks.
5. Focused tests and source-only diagnostics for the existing 24 slots/three retired sources. Generated artifacts remain under the configured application base.
6. A `pte` preparation/check entry that reports exact mapping, context sizes/cuts, deferrals, source membership, duplicates and saturation capability. Do not call an Ollama health check that generates text.

Tests must cover normalization ambiguity/repeated text, context-only vs center membership, cross-block roles, oversized units, optional context cuts, qualifier completeness, missing reported identity, conflicting provenance, deduplication and invalid cache reuse. Positive fixtures must show representable current and reported acts plus directed G2 pairs; unresolved mapping must remain a deferral. These are deterministic interface tests, not a semantic accuracy claim.

No inference, provider requests, model loading, new nomination execution queue, fresh sources, collector reopening, admission activation, thresholds, collection, recurrence/rates or pastor projection/scoring are included. No 10/12 criterion or 24-request authorization transfers from the superseded probe. If a later run is proposed, prepare a new fingerprint and actual local-model token/context/runtime/review ceilings for a separate decision.

## Cleanup performed and remaining

The first cleanup removes the obsolete active workflow, rather than deleting its history:

- `--context-extraction-probe --prepare` and `--run` return **RETIRED** before reaching the executor, even with the historical approved fingerprint.
- `--context-extraction-probe --check-only` verifies the original preparation bytes from Git commit `3c466bd`, plus the preserved input/panel/oracle and companion supersession decision. The original execution authority remains recorded at `baad411`.
- Calling the dormant old Python runner directly now fails its frozen implementation pins before credentials or transport. The frozen implementation source bytes remain recoverable from Git; they are not the current runnable experiment.
- Old packet documents and raw/generated data were not rewritten or deleted. Dormant helper modules remain only for history pending the later dependency-aware cleanup.

Remaining cleanup is the already planned retirement of failed collector/fresh-discovery execution surfaces after their import/hash dependencies are mapped. Shared source/serialization/admission support, accepted decisions, raw results/receipts, installed Ollama models and TypeSafe configuration remain protected. The unrelated untracked V2 evaluation files are untouched.

## Review commands and decision

```bash
pte analysis structure-readiness --handoff-proposal --check-only
pte analysis collector-retrieval-design --context-extraction-probe --check-only
```

**Recommendation: approve the provider-free implementation/preparation scope above.** It is the next bounded step inside the existing pipeline. Review its actual mapping/context/validation results before preparing one local-model nomination experiment. Do not revive the disconnected OpenAI probe or spend another iteration tuning the retired collector.
