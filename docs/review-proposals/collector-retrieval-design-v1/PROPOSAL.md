# Collector retrieval/composition design V1

**Decision requested: approve a narrow implementation of two separate retrieval/composition mechanisms and a prospective G3 reference policy. No implementation, model execution or evaluation is performed by this packet.** Brian's attached decision is recorded in [decision-v1.json](decision-v1.json): Fresh V3 scoped FAIL, G1 HOLD, punctuation-independent Source-unit Repair V1 successful for its bounded purpose and frozen. V3 is now development diagnostics only. Do not run Fresh V4 with the unchanged collector.

The smallest substantive change is to replace sentence/gloss-based pair selection with a bounded role index for G2, and replace sentence-as-act identity with exact act-core hypotheses for G3. These are independent workstreams. Neither changes what G1/G2/G3 measures or what A1 can admit. Geometry and retrieval remain hypotheses; uncertain voice/recipient/sufficiency still require source review.

## Evidence and design limits

The [accepted V3 review](../fresh-discovery-readiness-v3/SOURCE-REVIEW-v3.md) records 35 G2 misses: 24 nonlocal nomination/composition, six within-unit partition and five local multi-node composition. G3 has 27 cross-punctuation-unit misses. Geometric hits can also mix current address, Bible quotation, reported speech or prayer. Source-reviewed compatible lower bounds were 22/65 G2, 56/84 current G3 and 12/25 reported G3. They are not semantic successes or exhaustive compatible-recall estimates.

The source-unit repair stays byte-identical. Its bounded units become indexing leaves, not assertions of sentence, speaker or act identity. The new layer operates on source spans above and within those leaves. All V3 references, raw counts, omissions, results and accepted prior semantic/admission decisions remain immutable. No development target requires recovering all known misses.

## G2: directed explanatory-link retrieval

### 1. Build a small source-coordinate role lattice

For each frozen source unit, nominate at most three exact role descriptors: the intact unit and up to two competing clause/dependency boundary alternatives. A descriptor is one contiguous canonical span, plus its parent unit and a trace of proposed boundary/completion links. It carries no Bible/source/explanation label.

General boundary signals include quote introduction/termination, clause punctuation, conjunctions, condition/consequent structure and reporting transitions. They are not a phrase list mined from V3. When a gloss marker occurs within a sentence, it is one boundary signal rather than the only route. Deterministic boundary proposals must preserve negation, modal force, conditions and referents; an ambiguous split retains alternatives or a deferral. Three descriptors are a hard budget, not a promise that every parse is represented.

A role may cross punctuation units when a fragment, condition/consequent or unfinished quoted content needs completion. Completion follows a proposed dependency until the content is complete or a source/recipient switch or fixed frame bound blocks it. It does not enumerate every width of an adjacent window. Distinct narrow and completed alternatives share the descriptor/emission budget. Competing possible completions remain unestablished, not parser-certified truth. Exact completion policy, stable tie order and synthetic examples must be locked before real-source execution.

### 2. Replace the existing nomination budget

Keep the existing **8N G2 + 2N G3** upper bound, where N comes from the unchanged source-unit repair. Replacement G2 lanes are:

| Lane | Directed emissions at most | Purpose |
|---|---:|---|
| Local complete-role composition | 2N | One selected boundary pairing in both orientations; choose complete roles without requiring symmetric width |
| Within-unit clause partition | 2N | One selected split in both orientations, without treating a mixed whole sentence as a Bible anchor |
| Source-wide concept retrieval | 4N | For each seed unit, at most two other role matches, each proposed in both orientations |

A seed can query with its intact and clause representations, but all query/role variants compete for those same two remote matches. This prevents a Cartesian product of cuts, widths, neighbors and orientations. Duplicate span pairs are one candidate; unused lane capacity is not used to widen other lanes. Neither nearest-distance selection nor gloss words determine remote eligibility. Rank ties use canonical start/end offsets. Every rejected completion, displaced eligible nomination and frame-bound pair has an explicit reason/count; do not conceal the top-K loss by calling it absent evidence.

The index searches the whole source, while **each emitted complete frame/envelope still respects 6,000 characters**. A conceptually related distant pair beyond that existing representational limit is explicitly deferred. This proposal does not introduce discontinuous semantic request frames or drop intervening attribution to make a pair fit.

### 3. Make conceptual retrieval an explicit new component

Recommend one frozen local sentence encoder, `sentence-transformers/all-MiniLM-L6-v2`, for ranking only. Its [official model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) documents sentence/short-paragraph semantic-search embeddings and default truncation beyond 256 word pieces. No model was downloaded, loaded or executed for this proposal.

Before any execution, lock the immutable upstream revision, weight/tokenizer/config hashes, runtime, pooling, CPU numeric policy and deterministic tie rule. Do not compare models or fit weights/thresholds on V3. This is a new **retrieval** model dependency; it is not Jev tuning or a measurement replacement. Installation and actual local inference need the later execution authorization, even though they would make no provider requests.

Embed bounded ranking chunks with exact mappings back to the complete canonical descriptor. No silent tokenizer truncation: oversized roles are represented by bounded chunks within the descriptor budget or explicitly deferred. Ranking on a chunk never narrows the exported evidence role. Query each seed's descriptors against the source-local descriptor index; cap exact vector comparisons at 8,000,000 per source, using blockwise top-K rather than storing a quadratic pair inventory. Preflight rejects an over-budget source rather than silently changing the search method. Index size is at most 3N descriptors; CPU time, resident memory, encoded tokens and comparisons are recorded separately from emitted candidates.

Similarity can nominate a paraphrase without shared gloss vocabulary. It **cannot establish an explanatory relation**, direction, Bible provenance or even adequate conceptual recall. Topic-similar distractions are expected. Both directed candidate orientations stay separate and go to unchanged G2 measurement/admission later. The proposed encoder may miss exactly the low-overlap relationships motivating it; that is an explicit development risk. Replacing it after seeing results is a versioned new design, never an undisclosed hyperparameter search.

## G3: target identity before composition

### Prospective reference policy P1

An atomic target is the **smallest contiguous source utterance sufficient to express one addressed act toward one recipient scope under one source/voice configuration**, preserving conditions, negation, modality, required content and qualification. It can span punctuation units. It can support multiple frozen act fields; one field per target is not required. Source identity and recipient context belong in the envelope when they need not be uttered as part of the act.

Apply these rules before constructing any future census:

1. Keep a conditional or restrictive qualification with its act when deleting it would strengthen or change the exported claim. Keep required question content, anaphoric content or a necessary answer/completion. Do not use grammar alone to certify semantic sufficiency.
2. Separate independently sufficient commands, invitations, warnings or assurances even when adjacent and from the same speaker to the same audience. Shared topic, a list, or a rhetorical paragraph is insufficient reason to merge.
3. For repetition, keep exact occurrences independently retrievable. A separately reviewed same-event group can identify repetition within one local event. It does not erase source spans, grant discovery for an unfound occurrence, establish recurrence, or count duplicate geometries as unique evidence.
4. Keep current address, quoted/reported address, hypothetical/model speech, narration and prayer distinct. A current call to emulate quoted speech is an outer act with nested content; it does not turn the inner speaker's words into current preacher speech. Unknown nesting/recipient/adoption remains unresolved.
5. Independent supporting reasons may move to required source context; restrictive conditions or qualifications may not. A reason essential to the act's meaning stays in the target. Ambiguity is a diagnostic/deferred opportunity, not a convenient smaller positive.
6. Use exact source spans. No synthetic composite utterance, paraphrased role or removal of an intervening speaker turn. If a minimal coherent target cannot be represented by the existing contract, defer it. Do not modify measurement question semantics to accommodate the design.

This is a proposed **reference/target identity policy**, not an amendment to frozen G3 act questions. It needs approval before new reference authoring. It may change future denominators, so future results must carry their own policy version; historical exact-target results stay separately visible and cannot be compared as if the denominator were identical.

### Analysis of all 27 misses

The [exact-span diagnostic ledger](g3-diagnostic-analysis-v1.json) covers all 27 historical misses without generating replacement gold or rescoring:

| Design triage | Cases | Proposed treatment |
|---|---:|---|
| Dependent completion/qualification probes | 8 | Test cross-unit completion while preserving required referents, conditions, content or scope |
| Independently assertable cores / parallel acts | 16 | Review decomposition into minimal sufficient cores; retain reasons in context where legitimate |
| Repeated local request | 2 | Retrieve each exact occurrence; do not require an artificially wide repeated target |
| Nested modeled speech | 1 | Resolve outer act versus inner speech in source review; otherwise defer |

These are provisional design categories, not 27 certified repair labels. The dependent group can still contain more than one act; the parallel group can contain required qualifications. The policy must decide each independently, rather than using membership to force a split or join.

Examples: F3R951-G3-012 needs its conditional alleged-location setup; F3R1094-G3-026 needs the forgiveness qualification. F3R1094-G3-030 is an instruction whose following sentence supplies prayer content. F3R1094-G3-014 contains two independently expressed exhortations; F3R951-G3-041 repeats a card instruction. F3R951-G3-034 embeds modeled first-person commitment inside a current call to emulate. These examples motivate general rules, not source-ID or phrase-specific implementations.

### Candidate mechanism

Use the same small coordinate lattice as G2, but a separate G3 selector. For each frozen unit, at most two exact target hypotheses consume its G3 slots: a minimal core and, only where required, a dependent completion or competing boundary. Multiple independent cores within a unit compete for those two slots; excess eligible cores are explicitly deferred. Core selection traces cannot read references or expected act labels. Quote/reporting/recipient/prayer transitions block automatic merging. Suspected switches inside a unit trigger boundary alternatives; unresolved boundaries never receive compatible-source status automatically.

This replaces whole-unit/heuristic-continuation selection rather than appending more windows. It may trade breadth for cleaner targets. Required full-source framing remains in automatic envelopes, including named-source introductions and reporting continuation. Target boundaries and envelope context remain different objects. A reference containing two acts does not justify feeding a two-speaker mixture to Jev.

The collector can propose boundaries; it cannot reliably certify source/recipient identity from simple markers. No new automatic provenance oracle is claimed. A1 still requires supported, compatible, receipt-bound authority before evidence can reach the consumer. No mixed target is made usable merely by attaching metadata or an embedding score.

## Invariants and growth controls

- **Coordinates:** canonical source text and offsets round-trip unchanged; all roles are contiguous source substrings. Normalization exists only in index features.
- **Directed completeness:** G2 role order is explicit; neither reverse orientation nor completion variant inherits semantic support. Required attribution and conditions cannot be dropped to fit.
- **Target/context separation:** quotation/reporting context can be preserved without widening the semantic target. Mixed targets receive no source-compatibility credit by geometric engulfment.
- **Authority:** rank, parser hypotheses, source-only judgments and local encoder scores cannot create pastor credit or bypass A1 export/deserialization/consumer checks.
- **Bounds:** no ceiling increases: G2 ≤8N, G3 ≤2N, per-source G2/G3 ≤12,000, aggregate ≤20,000, G1 ≤200/source, frames/envelopes ≤6,000. The proposed 3N descriptor and comparison limits are additional resource limits, not evidence-expansion allowances.
- **Accountability:** counts by route/lane/source, density, displacement/deferral reasons, target/envelope distributions, controls and index resources are mandatory. Unmatched candidates are not false positives; deduplicated geometry is not unique usable evidence.
- **Versioning:** frozen segmentation, semantics, A1, .80 thresholds and old references remain pinned. Only a separately versioned collector and prospective P1 census can change. No V3 phrase overrides or per-source budgets.

## Tests required before any development evaluation

[synthetic-test-plan-v1.json](synthetic-test-plan-v1.json) specifies 16 focused deterministic scenarios, including non-gloss remote concepts, reverse direction, clause partition, complete roles, topic distractions, frame overflow, conditional acts, independent commands, repetition, prayer/report switches, narration, nested speech, Unicode coordinates, dense fanout and maximally positive but incompatible raw answers.

These are **proposed implementation tests**, not executed evidence that the repair works. Injected vector rankings and structural hypotheses test deterministic plumbing, limits and admission isolation. They cannot prove that a real encoder retrieves an explanatory relation or that real clause boundaries are correct. Test the actual unchanged admission integration for incompatible candidates without repeating the old semantic experiments or changing A1. No provider calls are needed.

## Staged implementation and confirmation

1. After design/P1 approval, implement only the new coordinate-role layer, separate G2/G3 selectors, local-encoder adapter, budget/displacement ledger, CLI preflight and focused tests. Keep the old collector executable for historical reproduction. Prepare the exact locked artifact manifest before loading the model. Do not implement automatic provenance resolution, new semantic fields or collection.
2. Prepare a fingerprint-bound, provider-free development packet over the retired sources. Brian runs its exact `pte` command only after separate execution authorization. Seal natural inventories without reference input, then match the unchanged historical slates diagnostically. Any P1 development annotations live in a separate ledger, never overwrite historical references. Report G2 and G3 separately, no requirement to recover all 35/27 misses, no iterative per-phrase optimization.
3. Codex source-audits selected targets/envelopes and all failures, controls and workload; freeze one reviewed implementation, model artifact and P1 policy. If the mechanism is not viable, stop and describe the limitation instead of opening a fresh confirmation.
4. Only then prepare a mechanically selected, previously unseen confirmation with the existing salted metadata/blinding/technical-source validation principles. No new source is selected now. Freeze inventory/envelopes/queue before an independent full-source P1 census. Seal references before opening candidates. Preserve G1 narrow opportunity definitions, aggregate floors, .80 aggregate targets and per-source gating only at n≥5; retain smaller cells as diagnostic.
5. Report complete-role, required-evidence and explicitly reviewed target/envelope supply separately. Prospectively test compatible supply at the same .80 targets: unreviewed alternatives cannot create PASS, and incomplete review is HOLD. Disclose independent-census omissions without post-match denominator repair. Include negative controls, mixed-source/recipient contacts, candidate/index resource distributions and duplicate geometries. Unknown precision/review time/economics remain unknown.
6. Source-only FAIL stops before Jev. A source-only PASS merely permits preparation of a separately bounded semantic/receipt/admission and timed-review packet, with exact queue/token/cost ceilings for Brian's execution decision. Keep existing operational limits (manual-envelope repair ≤.20, unresolved review deferral ≤.20, median active review ≤5 minutes, 480-minute review budget) as later measurements; this design establishes none of them.

## Recommendation and current authority

Recommend approving the small implementation plus P1 policy, with actual encoder loading, retired-source development execution and new source selection still requiring separately prepared, fingerprint-bound authorization. The local encoder is a concrete proposed dependency, not a claim of validated conceptual retrieval. This proposal does not authorize itself.

There is no current repair runner or paid command. The supplied read-only tie-in is:

```sh
pte analysis collector-retrieval-design --check-only
```

It validates packet hashes, recorded authority, frozen baseline pins and proposed budgets and prints this review location. It does not install/load a model, generate candidates, select sources, reannotate references or run evaluation.
