# Pastor profile implementation plan

**Active direction — 2026-10-20: reuse existing analytical evidence; repair a demonstrated gap at its responsible producer; aggregate and illustrate downstream.** This replaces the earlier experiment-led next steps. The [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) remains authoritative for the reader experience. [AGENTS.md](../AGENTS.md#reuse-and-responsibility-in-the-evidence-pipeline) makes this responsibility split a project rule.

The next work is a bounded provider-free integration and aggregation increment on **profile 318, recordings 4589 / 281 / 3973**. It must improve the working profile, not deliver another standalone inventory or feasibility study. This planning revision does not execute that increment, authorize new measurement semantics, or release any provider, collection, admission, benchmark or quotation hold.

## Delivery status — 2026-10-20

| Existing delivery | Status and treatment |
|---|---|
| Original milestones 1–3: readable assessment, at-a-glance view, evidence-to-wording rules and source navigation | Implemented. Retain the working V3 profile and existing observations. Brian's favorable product-language feedback is preserved; it is not acceptance of new measurement meanings. |
| Milestone 4: consequential-gap map | Delivered. Revise each actionable gap around actual reuse evidence and its insertion point; do not assume every unknown requires a new detector. |
| Ten source-reviewed generic readings and separate assurance adapter | Reusable reviewed proposals within their scope; all original G1 interpretations remain unchanged. They are not automatic discovery or production admission. |
| TypeSafe automatic binding V1/V2 and local connected extraction | Completed development failures; preserve results and diagnostics. Their next-extractor/model proposals are superseded as the active product roadmap. No further tuning, replay or new variant is scheduled. |
| Illustrative Ollama quotations | Optional downstream work, separately held. No quote/runtime preparation or execution is part of the immediate increment. |
| Benchmarks, ranking, single pastor scores, ministry-wide stability | Held. No new method, collection or production claim is authorized. |

The original sample has **158 eligible topic/treatment blocks** and **33 routed salvation blocks**. These counts describe the existing baseline, not a representative ministry corpus. Preserve reviewed membership, source versions and eligibility. Recording titles are metadata, not an accepted pastor identity label.

## Responsibility and insertion points

Processing order: **existing category/leaf observations → compatible evidence assembly → per-recording summaries → scoped profile patterns → supported point → eligible supporting block → optional illustrative quote**.

| Problem | First reuse | Responsible insertion point if something is missing | Downstream boundary |
|---|---|---|---|
| Evidence exists but the profile cannot see it | Current classification artifacts, leaf/refinement/composed caches, persisted analysis runs, reviewed bound records | Read-only loaders/resolvers and profile evidence assembly | Do not infer again to repair a reader/integration omission. |
| Support or refutation of a particular point | Relevant leaf's endorsement/polarity rules and any compatible G1 bound record | Relevant category-leaf producer; use an existing shared upstream binding component only where several producers need the same distinction | A generic critical/supportive treatment flag does not identify the evaluated proposition/object. The profile must not invent that link. |
| Preacher's own position versus quoted/reported speech | Existing leaf exclusions and source-use/voice/adoption distinctions | The same upstream leaf/claim producer or compatible shared attribution handling | Quotation use alone is not endorsement. Surface question form does not establish uncertainty or a listener response. |
| Conditions, concessions, reasons and evaluation targets | Existing leaf definitions, G1 condition/scope records, G2 nodes/relations | Producer of the affected local observation | Preserve attachment and stated bounds. Do not broaden conditions or convert a rationale into a salvation rule. |
| Listener action or circumstance-sensitive address | Listener-directive leaves and compatible G3 records | Existing directive/address producer | A topic, practical-application flag or reported prayer is not an adopted current-listener act or evidence of real listener circumstances. |
| Emphasis, repeated treatment and variation | Existing topic summaries and compatible local observations | Per-recording aggregation, then profile description rules | Model probabilities are not pastor scores; overlapping blocks are not independent sermons. |
| Missing, conflicting or limited evidence | Existing routing, measurement, eligibility, scope and uncertainty states | Aggregation and presentation, with producer provenance retained | Unmeasured, unrouted, below threshold, unresolved and contrary evidence remain distinct. |
| A concrete example of an established point | Eligible supporting blocks already linked to its observations | Deterministic profile example selection | A thematically related block is insufficient if it contradicts, merely reports or does not support the stated point. |
| A concise exemplar quotation | The established point and selected block | Final optional quote selection and literal validation | Find the relevant statement; do not rediscover theology or use a quote to supply missing analytical authority. |
| Sampling, identity or comparability absent | Existing source/membership/metadata and approved methods | The corresponding coverage, metadata or future comparison work | Keep unknowns and sample limits. Do not commission a new semantic measurement to solve these problems. |

## Existing code to reuse

| Responsibility | Existing entry points and contracts |
|---|---|
| Read-only scope, eligibility and source identity | `profile_analysis.py`, `segment_cache_inventory.py`, `segment_profile_view.py`, `sermon_topic_projection.py` |
| Topic and treatment evidence | `sermon_topics.py`, `sermon_topic_profile_analysis.py`, `sermon_semantic_dimensions.py` |
| Salvation relationships | `sermon_salvation_relationships.py`: nine admitted leaves, frozen routing/thresholds and three unresolved relationships stay within their meanings |
| Directive, public-treatment and source-material leaves | `sermon_leaf_packs.py`; public-treatment scope checks in `sermon_public_life_review.py`; existing `TypeSafeBlockCache` identity/payload readers in `sermon_classifier_typesafe.py` |
| Existing reuse hooks | `profile_description.load`, `leaf_reuse_checks`, `segment_cache_inventory.compatible_layers`; extend their read-only assembly instead of starting a second census |
| Bound claims, development and address | Existing G1/G2/G3 contracts and their actual implemented/validated scopes; `theological_binding.py`, `binding_evidence.py`, `assurance_binding_adapter.py` and the ten reviewed records where compatible |
| Scripture information | Existing Scripture/reference/alignment and sermon-analysis artifacts where compatible; citation occurrence alone cannot establish exposition or cross-book reasoning |
| Profile wording, evidence ledger and UI | `profile_description.py`, `profile_presentation.py`, `profile_capability_review.py` and current CLI/rendering |

No row means that compatible observations for these three recordings have already been found. Distinguish **contract designed / producer implemented / judgment validated / result persisted / observation admitted / profile integrated**. A missing exact full-pack identity is a bounded lookup result, not proof that each independent leaf or compatible prior composition is absent. Conversely, a historical pilot receipt cannot be relabeled as a production result for a different source window.

## Active work sequence

### R1 — integrate reusable evidence into the existing profile claim ledger

**First implementation slice; provider-free.** Work only backward from the current reader claims, the four product families and the existing consequential gaps. Reuse the current bounded checks; do not rescan a corpus or write another general inventory report before coding.

1. For each point already displayed or consequentially withheld, identify its exact required observation and current upstream owner. Keep topic attention, treatment, local relationships and adopted positions separate.
2. Check the existing materialization and applicable registered pack, individual-leaf/refinement and saved composition paths for these recordings. Use safe readers only: no assessment, hydration, refill or composition API that can silently infer or write caches. Inspect relevant existing Scripture/G1/G2/G3 results only when the point calls for them.
3. Integrate compatible observations through the existing loaders. Preserve source/context identity, question meaning/digest, requested/resolved model/provenance, applicable policy/threshold, routing and eligibility. A reuse adapter must document why a saved leaf remains compatible; a shared label or a newer schema name is insufficient.
4. Attach supply status to the existing claim/gap record, with: reader point/claim ID; required distinction; producer/contract; inspected artifact/cache identity and outcome; compatibility or rejection reason; available observation/source links; and the precise missing field when unresolved.
5. Render the supported profile with that evidence integrated and unknowns retained. Preserve reviewed proposals as proposals; do not turn them into admitted automatic measurements.

**Deliverable:** one runnable profile update, its claim-to-observation trace and a short changed/withheld explanation in the existing HTML/Markdown/JSON packet. A separate inventory document is not the completion condition. If no additional evidence is compatible, the deliverable still records the bounded reasons and correctly distinguishes an integration gap from an upstream/data gap; it must not claim newly supported findings.

**Exit checks:** every reused record has compatible provenance; no duplicate inference or inference/cache write occurs; full-pack absence cannot silently mark all constituent leaves missing; conflicting/incompatible data is surfaced; original observations, G1 interpretations and V3 artifacts remain unchanged. Use a new artifact version for changed profile behavior.

### R2 — route only a consequential, demonstrated semantic gap upstream

**Conditional branch, not a prerequisite for shipping R1/R3.** A gap must first survive the R1 reuse check. Codex prepares a concrete decision row; Brian is not asked to annotate or design an experiment.

Each row must contain:

- The exact reader-facing statement that cannot be supported and why it matters.
- The available leaf/contract/answer, inspected reuse outcomes and the exact missing distinction.
- The smallest responsible insertion point, named function/module and downstream consumer.
- The proposed code/contract change, an alternative that avoids new inference, positive/negative/ambiguous source-backed controls, and an acceptance/failure rule.
- Whether the change is an adapter fix, a changed measurement or new collection, and the precise applicable authorization boundary.

**Concrete example:** a public-treatment result records `critical`, but the desired statement says the preacher rejects proposition X. First check whether existing compatible output already binds the criticism to X and to the preacher. If it does, expose that output. If it does not, propose the smallest target/voice/adoption binding at that leaf's producer. Do not ask the final summarizer or quote selector to classify support/refutation, and do not launch general proposition discovery to solve this one relationship.

**Exit:** either reuse/integration resolves the point, a single minimal upstream change is ready for a specific decision, or the point remains explicitly unknown. Held G1 expansion, new measurement semantics and provider calls still require their separate authorization. Existing supported profile work continues in every case. No model selection or provider run is the default next step.

### R3 — aggregate supported observations into within-sample patterns

**Provider-free; follows R1 using available evidence.** Extend the existing deterministic description/reader rules rather than generating an independent assessment from transcripts.

- Assemble each recording first, then compare the three recording summaries. Retain the exact supporting observations, contrary evidence and measured/missing state by recording.
- Reuse current topic summaries and frozen local observation rules. Do not create a probability average, numerical score, qualitative bin or threshold merely to obtain stronger wording. Additional wording/aggregation rules must state their inputs, scope, deduplication, counterevidence and withholding behavior and remain reviewable proposals until accepted where required.
- Deduplicate repeated references, overlapping source windows and known duplicate content using existing identity/provenance. Distinct blocks do not establish independent teaching occasions. Do not claim independence or complete opportunity coverage where it is unknown.
- Describe what is shared or variable **in these recordings**. Frequency, predominance, “consistent teaching,” chronological change and ministry-wide tendencies require evidence/denominators not supplied by this sample. Upload dates are not sermon dates.
- Preserve coexisting themes and qualified differences. Do not manufacture doctrinal opposition, average conflicting propositions into a middle position, or turn missingness into a negative trait.

**Deliverable:** readable assessment, at-a-glance summaries and recording-level comparison/variation, each linked to the claim ledger. Unknown dimensions stay visible and do not block supported sections.

**Exit:** every substantive clause traces to a stated descriptive rule and eligible observations; removal of an example quote cannot change the analytical conclusion; a single unusually strong block cannot establish a sample-wide trend. Tests cover duplicate/missing/contrary evidence and wording scope, not just snapshots of generated prose.

### R4 — select supporting blocks for already-established points

**Provider-free; follows R3.** Use the point's eligible support set, not a fresh search over all text or a new inference pass.

For each point, retain its claim/rule ID, recording-level support, selected CENTER block with source hash/time/eligibility, the support reason, any necessary attribution/qualification and relevant contrary evidence. Prefer existing support strength and an inspectable representative example. Use deterministic time/block-ID ties. Preserve an unknown selection if no eligible block supports the point. An example illustrates the aggregate finding; it does not establish frequency or coverage.

**Deliverable:** a full relevant source block behind each eligible example link, supplied with the established point. Keep current complete-block examples useful before optional excerpt extraction.

**Exit:** no quote is needed to establish the point; the block supports that particular point rather than merely sharing its topic; incompatible, reported-only or contradictory material cannot silently become positive evidence. Do not add a second semantic classifier here to repair an upstream gap.

### R5 — optional illustrative quotations, after separate authorization

This is the existing held milestone 5. Give the configured Ollama quote backend the **already-established point**, selected complete eligible CENTER block and distinctly labeled eligible BEFORE/AFTER neighbors with real identities/bounds. Ask for the most relevant contiguous statement illustrating that point. Substantive support must come from CENTER; neighbors only complete the same thought or preserve attribution/qualifications/recipient identity.

Code verifies verbatim location, source order, center anchoring and provenance; ambiguous repeated locations, stitching, paraphrases or missing qualifications withhold the excerpt. Quotes cannot create claims, classify support/refutation, fix a failed leaf or alter measurements. No TypeSafe quote-selection substitution, general theological extraction, automatic context expansion or upstream minimal-span prerequisite is included.

Only this task's model/digest, prompt/schema, runtime/output/context limits, cache identity and exact bounded command should be prepared if/when authorized. The failed connected theological extractor is not the quote implementation and supplies no quotation authority. Quote execution is not authorized by this revision.

## Sequence, review and authorization

**Main path:** R1 integration → R3 sample aggregation → R4 supporting blocks → Brian reviews the concrete profile. **Conditional branch:** R2 only for a named blocked statement; unsupported points remain unknown. **Optional held follow-up:** R5 quotations. Benchmarks, broader collection and stability claims are outside this sequence.

The immediate next coding work is R1 in the existing profile loader/ledger/rendering path, with compatible evidence integrated in the same slice. This planning request does not itself execute those code changes or release held semantic/provider work. It does not require a new planning document, global inventory or generic binding experiment before implementation can begin under the user's existing authorizations.

Use the existing entry points for profile delivery and verification; new user-facing checks must also attach to `pte`:

```bash
pte analysis structure-readiness --segment-view --description --json
pte analysis structure-readiness --segment-view --description --check-only --json
pte analysis structure-readiness --segment-plan --json
```

Current commands reproduce the existing V3 feature; R1/R3/R4 extensions described here are not yet implemented. Changed outputs must use a new version so the current profile remains reproducible. Generated reports/caches/receipts belong in the app base; intentional plan/contracts and curated inputs belong in source control.

Codex implements, prepares exact cases/defaults/commands, interprets results and recommends a next action. Brian runs bounded dataset validation, reviews the concrete result, makes minor edits and decides consequential held choices. No open-ended case selection, JSON authoring or annotation is assigned to him.

## Scope control and stopping rules

1. One active product slice at a time. Every task must name its reader-visible improvement and responsible existing module before adding code or inference.
2. Keep a completed R1/R3/R4 result deliverable even if a conditional R2 gap remains unresolved. Do not let an unsupported desired sentence restart the whole product pipeline.
3. Never treat a contract, synthetic test or bounded feasibility PASS as persisted/admitted evidence for profile 318. Never reinterpret a frozen leaf to obtain a more complete-looking profile.
4. Do not reopen TypeSafe V1/V2, connected extraction, closed collector/discovery panels or exact-span nomination as an implicit next step. A smaller schema, stronger model or another synthetic round is not the active plan. A specific future proposal needs a demonstrated upstream gap and separate user decision.
5. A bounded validation result has a predeclared acceptance/failure decision. If it fails, record the failure, preserve the usable profile, and present the smallest concrete decision; do not automatically change prompts, thresholds, models or sample size.
6. Run focused tests and inexpensive checks only; no large fixture/corpus evaluation or monitoring. Brian executes dataset commands. Validate eligibility/provenance, conservative aggregation and point/block linkage. Optional quote tests must also prove analytical output is unchanged by absent/rejected quotations.
7. No new provider/model calls, broader collection, changed measurement/admission rules, production activation, benchmark similarity/ranking, pastor score, ministry-wide stability claim or Ollama quotation execution is authorized here.

## Milestone 1 — implement the descriptive profile contract and worked example

**Already delivered.** The versioned record, worked profile, evidence links and unknowns remain the baseline. R1 extends its trace/reuse handling without replacing it. The original implementation and verification history is preserved in the snapshot linked below.

## Milestone 2 — implement evidence-to-description rules

**Already delivered; proposed wording rules remain reviewable.** R3 builds from these rules and preserves the four analytical families, frozen leaf meanings, topic-versus-adoption distinction and unknowns. No new score is introduced.

## Milestone 3 — read-only profile screen and CLI

**Already delivered.** R1/R3/R4 must update this screen through its existing CLI, not create another standalone assessment product. Assessment and at-a-glance findings precede supporting observations and source text.

## Milestone 4 — consequential gaps

**Initial gap/code map delivered.** R1/R2 revise actionable rows around named reader points, demonstrated reuse outcomes and the earliest responsible insertion point. A missing example excerpt is presentation work, not a new analytical measurement.

## Active increment — reusable proposition binding separated from assurance

**Existing reusable support, not the next generic extraction project.** Keep the ten source-reviewed proposals, unchanged assurance adapter and compatible G2/G3 structures available within their actual scopes. See [the reusable binding workflow](PROFILE_PROPOSITION_BINDING.md). No automatic admission or profile-wide adoption is inferred.

## Historical evidence and superseded directions

The [pre-realignment implementation snapshot](PASTOR_PROFILE_IMPLEMENTATION_PLAN.historical-before-reuse-first-2026-10-20.md) preserves the complete prior roadmap, commits, verification and experimental next-step recommendations. The [product snapshot](PASTOR_PROFILE_PRODUCT_PLAN.historical-before-reuse-first-2026-10-20.md) preserves its corresponding status narrative. These are history, not active instructions.

The [TypeSafe development results](PROFILE_BINDING_DEVELOPMENT.md), [connected extraction failure/diagnostics](PROFILE_CONNECTED_BINDING.md), existing G1/G2/G3/A1 decisions and raw app-base artifacts remain unchanged. Their failures establish limits of those experiments; they do not invalidate category-leaf semantics or establish that the profile needs another extractor. Earlier suggestions to proceed with a different extraction backend or a new minimal extraction experiment are superseded by R1–R4 unless Brian explicitly reopens a specific upstream gap.
