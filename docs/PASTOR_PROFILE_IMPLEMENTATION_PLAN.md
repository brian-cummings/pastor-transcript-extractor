# Pastor profile implementation plan

**Active direction — 2026-10-20: reuse existing analytical evidence; repair a demonstrated gap at its responsible producer; aggregate and illustrate downstream.** This replaces the earlier experiment-led next steps. The [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) remains authoritative for the reader experience. [AGENTS.md](../AGENTS.md#reuse-and-responsibility-in-the-evidence-pipeline) makes this responsibility split a project rule.

The current increment is bounded provider-free integration and aggregation on **profile 318, recordings 4589 / 281 / 3973**. It must improve the working profile, not deliver another standalone inventory or feasibility study. R1/R3/R4 are implemented in V4; Brian generated the bounded profile and Codex verified the saved artifact on 2026-10-20. Brian’s subsequent review finds the descriptions too high level; Brian generated the provider-free V5 revision on 2026-10-21; Codex verified the saved artifact and inspected its wording. Brian’s concrete wording acceptance remains pending. This delivery does not authorize new measurement semantics or release any provider, collection, admission, benchmark or quotation hold.

**Latest direction — 2026-10-21:** Brian says V5 is getting better and requests an Ollama final synthesis for a more natural pastor-level portrait. Brian executed S1 once; its output was rejected and has now been inspected. No usable editorial portrait was produced. Brian approved the required-portrait contract correction; S1 V2 is implemented and awaits his bounded run. V5 and all analytical meanings remain unchanged; no model or metadata calls were made during implementation. “90%+ of OpenAI product quality” and dramatically better economics are product hypotheses, not measured outcomes.

## Delivery status — 2026-10-20

**Reuse increment delivered; bounded generation and artifact checks passed.** V4 integrates compatible saved leaf answers and source-reviewed binding proposals, attaches claim/gap supply traces, adds recording comparisons and selects point-linked full supporting blocks. Authored bindings and raw leaf judgments retain their non-production status. Brian’s run produced 15 reader claims, 24 underlying claims, 39 selected example sets, ten reused source-reviewed proposals and eight consequential gaps. No additional compatible raw leaf answers or exact-current Scripture runs were found at the checked identities; this is not global cache absence. Seals, current source/implementation hashes, claim references and HTML links passed direct checks. Browser security blocked local-file visual inspection, so Codex reviewed the generated HTML and Markdown directly; visual/wording acceptance remains Brian’s.

**Product outcome correction:** the V4 run proves working assembly, provenance and navigation, not sufficient descriptive usefulness. Brian finds the profile too high level. The implemented V5 increment is **D1–D4: explain existing findings with concrete local examples**, using the four reviewed style descriptions, ten source-reviewed local readings, existing claim ledger and supporting blocks. No listener-directive run or new measurement is the default follow-up. V5 passed 104 focused profile checks. Brian’s actual V5 run produced 14 explanatory points (four style examples and ten local proposals), 29 reader claims, 53 selected example sets, no withheld descriptions and eight retained gaps. Codex checked seals, source/implementation hashes, clause and passage links, unchanged raw observations and unchanged reviewed binding/assurance records against V4. The assessment is more concrete, but some qualification language remains formal; reader acceptance is not inferred. Technical delivery and reader acceptance remain separate.

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

The implementation extends `profile_description.py` / `profile_presentation.py` with narrow pure helpers `profile_evidence_supply.py`, `profile_sample_patterns.py`, `profile_supporting_blocks.py` and `profile_explanatory_descriptions.py`. `profile_capability_review.py` now reports current consequential gaps rather than requesting another completed pilot.

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

## Current increment S1 — local editorial synthesis of the existing profile

**V1 rejected and preserved; approved V2 contract correction implemented, awaiting Brian’s run.** `profile_synthesis.py` and the existing `pte` analysis CLI add one optional local Ollama writing pass over the established V5 description packet. This is downstream editorial composition, not a reopened theological extractor, new measurement, quotation task or automatic production admission. Brian executes the bounded command; Codex has not called Ollama or probed installed-model metadata.

The model receives only whitelisted existing reader claims and reviewed explanatory points with their source IDs, recording scope, voice/use, conditions, qualifications and unknowns. Where a generic summary’s exact supporting observations are already explained by reviewed points, prefer those richer points instead of duplicating the generic summary. No full transcript, raw block dump, probability inventory, historical binding experiment or external pastor knowledge enters the request. V5 remains the source of analytical authority and fallback.

**Writing task:** connect the supplied findings into natural prose about who the preacher appears to be **in these recordings**, what stands out in this sample and the four existing analytical families. Each sentence cites short supplied source handles; code maps these to exact existing claim IDs, and the response schema enumerates the permitted handles. Do not turn examples into a dominant method, usual sermon structure, unique trait, quality rating, complete theology, real listener response or ministry-wide stability. Local proposals keep their status; saving desire, reported/adopted speech, invitations and qualifications retain their meanings. Missing sections stay explicitly unavailable rather than being filled speculatively.

**Comparison and confidence:** “Who they are most like” stays visibly unavailable. No compatible benchmark inputs or validated comparison method were supplied; model familiarity with public preachers cannot substitute. Confidence is code-owned coverage/limitations (selected recordings and existing block counts), not an LLM certainty score, High/Moderate/Low scale or calibrated percentage. A portrait of what stands out is not evidence of distinctiveness relative to other pastors.

**Bounded runtime:** reuse the configured installed local Ollama model and loopback endpoint, with a pinned model digest, temperature 0, context ceiling 32,768 and output ceiling 3,072 tokens. One generation per exact source/prompt/schema/configuration identity; metadata pin/check before and after. Preserve raw response and actual token/timing receipts. No health-test generation, model pulls, cloud/provider fallback, automatic retries, prompt repair or model variants. A conservative preparation budget includes model-visible input bytes, schema and a format allowance; reject oversized inputs without truncating evidence. No installed model is assumed until Brian runs the command.

**Output and review:** a clearly labeled editorial draft appears above the complete existing profile, with links to the cited descriptions and source passages. Store original request/raw response, compiled draft, unchanged source profile and HTML/Markdown/JSON review packet under the app base in `evaluation/pastor-profile-synthesis-v1/`. Schema/citation checks verify shape and source pointers only. They cannot prove that a paraphrase is entailed or that a combination preserves qualifications. The draft is never automatically accepted, and it does not update raw observations, G1 interpretations, membership, measurements, reader acceptance or the original V5 files. A rejected/truncated/changed-model output is withheld and retained for inspection, not repaired or rerun.

Use the [synthesis workflow](PASTOR_PROFILE_SYNTHESIS.md):

```bash
pte analysis profile-synthesis --prepare --json
pte analysis profile-synthesis --run --json
```

Preparation is read-only and does not contact Ollama. Brian’s `--run` is the single bounded execution step. Cached inspection uses `pte analysis profile-synthesis --json`; read-only reconstruction uses `--check-only --json`. Codex then checks every generated sentence against its cited findings and qualifications, reports unsupported combinations/comparisons, assesses naturalness and recommends acceptance or a specific correction. No citation-valid draft or attractive prose constitutes semantic acceptance. No claim that the quality/economics target was reached follows from a successful request.

**Actual outcome — 2026-10-21:** Brian’s `gemma3:4b` run returned one `theological_orientation` section with three sentences, not a portrait. The validator correctly rejected it: `A unique portrait section is required`. It stopped normally at 147 output tokens, well below 3,072; this was not truncation or context overflow. Usage: 5,863 input tokens, 147 output tokens, model duration 26.409 seconds, one generation and two metadata reads. Codex made no additional provider/metadata calls. Original response and useful V5 fallback remain preserved.

**Sentence review:** sentences 1 and 2 copy S1 and S2 verbatim, retaining topic-attention descriptions but adding no synthesis. Sentence 3 introduces plural “preachers,” “consistently emphasize,” and an inference from subject attention to the importance of aligned living and spiritual development. S1/S2 explicitly limit themselves to attention, not agreement; this sentence is not accepted. Relabeling the returned section as a portrait would not resolve that semantic problem.

**Concrete implementation finding and next decision:** the prompt requires a portrait, but the supplied JSON schema permits any one optional section; only the post-response validator enforces portrait presence. This contract mismatch allowed the observed output shape, although it does not establish the cause of the model’s thin prose. Recommend a narrowly versioned correction making the portrait a required schema property, preserving sentence citations and every semantic check, before considering one further same-model run. Brian approved this specific correction in chat. V2 now requires a nonempty `portrait` property in the generation schema; optional dimensions cannot use the portrait key. The parser preserves the same internal rendering shape without repairing prose, and all citations, scope/semantic review and request limits remain. The evidence packet, configured model and analytical meanings are unchanged. V2 uses a separate `pastor-profile-synthesis-v2` artifact directory; V1 is preserved. Brian executes the next bounded run; no model request or metadata probe was made during implementation. No further variants or automatic retries are authorized. Do not add transcripts, measurements or speculative belief wording to compensate. Quality/economics parity remains unmeasured.

**Exit:** a concrete synthesis draft and transparent evidence are ready for review, or an inspectable rejection explains the exact failure. Keep the useful V5 profile in either case. All holds on other provider work, new measurements/admission, collection, benchmark/ranking, ministry stability and Ollama quotation execution remain intact. This authorization is specifically for the editorial workflow; it does not reopen previous binding experiments.

## Next increment — useful descriptions from existing evidence

**Status: V5 generated by Brian and saved-artifact checks passed on 2026-10-21; concrete wording acceptance pending.** This is a bounded extension of R3/R4 presentation, after completed R1 integration. Keep profile 318 and its three recordings fixed. The Henry Johnson example supplied by Brian is a reference for specificity and readability, not evidence about this pastor, accepted theology, or wording the system must reproduce. Its 17-sermon coverage does not transfer to this three-recording sample.

**Reader outcome to review:** replace lists such as “biblical explanation + practical application” with short accounts of what the preacher explains, how he develops a point and what he asks listeners to consider, where existing evidence establishes those details. A reader should be able to describe a concrete example in ordinary language before opening Technical details.

### D1 — assemble point-level descriptions from existing records

Extend `profile_presentation.build_reader` and its existing claim records; reuse `profile_description` / `profile_evidence_supply` / `profile_supporting_blocks` outputs. Do not introduce another inference service or general transcript summarizer.

For each usable point, assemble a small additive description record: reader point/claim ID, plain-language descriptor and explanation, example, supporting observation/reviewed-binding IDs and passage links, recording scope, qualifications, counterevidence, interpretation/proposal status and source compatibility. Every substantive clause retains a trace. Existing four style-review descriptions and ten reviewed local readings are the initial concrete inputs; generic assembly must also work with fewer or no such records.

Use existing explanatory content rather than asking a model to rediscover meaning from a probability or topic label. A topic label supplies attention only. A treatment candidate supplies a window for inspection, not an authored explanation. Reviewed bindings can supply local proposed interpretations with their existing voice/use/scope distinctions; their display does not confer production admission or whole-sermon coverage.

### D2 — explain findings with concrete examples

Build short per-point and per-recording accounts from D1. Lead with the content of the supported example and explain the existing relationship in ordinary language. Do not call an account a complete sermon summary when the reviewed evidence covers selected passages only. Preserve separate examples as separate examples; do not invent a connected argument, purpose, causal chain or dominant method from their co-occurrence.

| Thin current wording | Proposed reader-facing description | Existing evidence and limit |
|---|---|---|
| Biblical explanation | Explains disputed wording in a biblical passage | Reviewed Laodicea passage distinguishes a title applied to Jesus from the assertion that Jesus was created. Local example, not a prevalence or interpretive-quality rating. |
| Storytelling and illustration | Makes a biblical image concrete through personal experience | Reviewed earthquake account gives the sermon’s “shaking” image a personal setting. Do not infer characteristic humor or storytelling skill. |
| Practical application | Connects dependence on Jesus with everyday religious practices | Reviewed application names Bible reading, prayer, church participation, study and sharing faith. Do not infer listener compliance or saving conditions. |
| Grace and initiative | Presents salvation through mercy rather than personal merit in a reviewed appeal | `P1-mercy` retains explicit endorsement of the invited account. A local proposed reading, not a blanket doctrinal classification. |
| Pastoral approach unknown | Offers reassurance and challenges spiritual neutrality in the reviewed passages | `P2-saving-desire`, `P2-warning` and `P2-middle-critique` retain their separate use and qualifications. Do not infer their relative balance, frequency or salvation-loss mechanism. |

These are proposed translations of existing evidence, not fixed expected outputs or new measurement definitions. Where the required explanation is unavailable, retain the narrower supported description and precise unknown; do not use a nearby topic or unreviewed block as a substitute.

### D3 — build the readable overview and at-a-glance from those accounts

Compose the assessment from the D1/D2 records; do not write an independent assessment from raw transcripts. Preserve the four analytical families and evidence-first processing. Use specific explanations and examples in the overview, concise explanatory phrases in the at-a-glance table and fuller recording accounts underneath. Repetition of taxonomy labels is not adequate synthesis.

Move useful reviewed local readings into the main reading path, visibly labeled as proposals with local scope. Do not hide all of their content behind a blanket statement that affirmed positions are unknown. Conversely, do not represent ten authored readings as automatic discovery or a complete theological portrait. State what the local readings establish/propose and what remains unknown at broader scope.

Consolidate repeated general limitations in a visible sample-limits section. Keep a qualification next to its claim whenever removing it would change meaning—for example, invitation versus actual listener response, saving desire versus completed salvation, and warning versus a particular loss-of-salvation doctrine. Unknowns and counterevidence remain accessible and substantive; they are not merely hidden to make the prose smoother.

Do not import stronger judgments from Brian’s example: theological-school alignment, “strongly grace-oriented,” usual sermon structure, strongest skill, historical reliability, or characteristic humor require their own evidence and are not inferred here.

### D4 — verify and deliver the revised profile through the existing CLI

Ship a single revised HTML/Markdown/JSON profile packet, not a separate descriptive proposal that becomes another implementation gate. Use a new description/reader artifact version (proposed V5), retain V4 reproducibility and include description assembly inputs in the manifest. Extend the existing `pte analysis structure-readiness --segment-view --description` workflow; no standalone script is the user entry point. The existing command now targets V5; existing V4 artifacts and the V1 authored review input remain preserved. A V2 authored presentation input adds concise descriptors to the unchanged four reviewed explanations; it is not a new measurement or validation result.

Focused checks must cover clause-to-evidence links; exact source/review compatibility; missing or fewer reviewed records; preservation of speaker, adoption, invitation, qualification and contrary-evidence distinctions; unchanged original observations/G1 interpretation; and identical analytical authority with absent/rejected examples or quotes. Include positive, negative and ambiguous existing controls; tests of string presence alone cannot establish semantic correctness. Generic fallback must not produce invented explanations or become tuned to the three-sermon example.

Brian runs the same bounded generation command when the implementation is ready. Codex inspects the receipt and concrete output and recommends revisions. Do not declare reader acceptance from generated counts, green tests or syntactically valid prose.

### Expected outcomes and acceptance

- **Useful assessment:** the overview explains supported content and methods with concrete local examples instead of a category inventory. Every substantive clause is source-linked.
- **Useful at-a-glance:** each characterized dimension has a plain-language explanation and an example link; unsupported dimensions remain explicit unknowns.
- **Useful recording accounts:** selected reviewed passages explain what is being taught or illustrated; they are not represented as comprehensive sermon summaries.
- **Faithful local readings:** relevant reviewed proposals appear in the main reading path with their original voice/adoption/scope/qualification boundaries and status intact.
- **Defensible limits:** general disclaimers are consolidated while meaning-changing qualifications, contrary evidence and genuine gaps remain visible.
- **No new analytical dependency:** no provider/model calls, full-transcript OpenAI processing, new collection, new measurement/admission, score, benchmark, stability claim or Ollama quotation execution. No new fixed number of descriptors, summaries or claims is a completion target.
- **Concrete handoff:** one runnable versioned packet, its claim/evidence trace and changed/withheld explanation, focused checks and exact CLI command. Brian’s assessment of reader usefulness is recorded separately from technical delivery.

**Order:** D1 description records → D2 concrete accounts → D3 overview/at-a-glance → D4 verification and profile review. This sequence is implemented and its bounded V5 artifact has been inspected; reader acceptance remains pending; R2 upstream repair remains conditional only after this use of existing evidence exposes a specific consequential gap. Do not start listener-directive inference, another binding experiment, model selection or a new measurement before completing this description increment.

## Active work sequence

### R1 — integrate reusable evidence into the existing profile claim ledger

**Implemented; provider-free; bounded artifact checks passed.** Work only backward from the current reader claims, the four product families and the existing consequential gaps. Reuse the current bounded checks; do not rescan a corpus or write another general inventory report before coding.

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

**Implemented; provider-free; follows R1 using available evidence.** Extend the existing deterministic description/reader rules rather than generating an independent assessment from transcripts.

- Assemble each recording first, then compare the three recording summaries. Retain the exact supporting observations, contrary evidence and measured/missing state by recording.
- Reuse current topic summaries and frozen local observation rules. Do not create a probability average, numerical score, qualitative bin or threshold merely to obtain stronger wording. Additional wording/aggregation rules must state their inputs, scope, deduplication, counterevidence and withholding behavior and remain reviewable proposals until accepted where required.
- Deduplicate repeated references, overlapping source windows and known duplicate content using existing identity/provenance. Distinct blocks do not establish independent teaching occasions. Do not claim independence or complete opportunity coverage where it is unknown.
- Describe what is shared or variable **in these recordings**. Frequency, predominance, “consistent teaching,” chronological change and ministry-wide tendencies require evidence/denominators not supplied by this sample. Upload dates are not sermon dates.
- Preserve coexisting themes and qualified differences. Do not manufacture doctrinal opposition, average conflicting propositions into a middle position, or turn missingness into a negative trait.

**Deliverable:** readable assessment, at-a-glance summaries and recording-level comparison/variation, each linked to the claim ledger. Unknown dimensions stay visible and do not block supported sections.

**Exit:** every substantive clause traces to a stated descriptive rule and eligible observations; removal of an example quote cannot change the analytical conclusion; a single unusually strong block cannot establish a sample-wide trend. Tests cover duplicate/missing/contrary evidence and wording scope, not just snapshots of generated prose.

### R4 — select supporting blocks for already-established points

**Implemented; provider-free; follows R3.** Use the point's eligible support set, not a fresh search over all text or a new inference pass.

For each point, retain its claim/rule ID, recording-level support, selected CENTER block with source hash/time/eligibility, the support reason, any necessary attribution/qualification and relevant contrary evidence. Prefer existing support strength and an inspectable representative example. Use deterministic time/block-ID ties. Preserve an unknown selection if no eligible block supports the point. An example illustrates the aggregate finding; it does not establish frequency or coverage.

**Deliverable:** a full relevant source block behind each eligible example link, supplied with the established point. Keep current complete-block examples useful before optional excerpt extraction.

**Exit:** no quote is needed to establish the point; the block supports that particular point rather than merely sharing its topic; incompatible, reported-only or contradictory material cannot silently become positive evidence. Do not add a second semantic classifier here to repair an upstream gap.

### R5 — optional illustrative quotations, after separate authorization

This is the existing held milestone 5. Give the configured Ollama quote backend the **already-established point**, selected complete eligible CENTER block and distinctly labeled eligible BEFORE/AFTER neighbors with real identities/bounds. Ask for the most relevant contiguous statement illustrating that point. Substantive support must come from CENTER; neighbors only complete the same thought or preserve attribution/qualifications/recipient identity.

Code verifies verbatim location, source order, center anchoring and provenance; ambiguous repeated locations, stitching, paraphrases or missing qualifications withhold the excerpt. Quotes cannot create claims, classify support/refutation, fix a failed leaf or alter measurements. No TypeSafe quote-selection substitution, general theological extraction, automatic context expansion or upstream minimal-span prerequisite is included.

Only this task's model/digest, prompt/schema, runtime/output/context limits, cache identity and exact bounded command should be prepared if/when authorized. The failed connected theological extractor is not the quote implementation and supplies no quotation authority. Quote execution is not authorized by this revision.

## Sequence, review and authorization

**Delivered foundation:** R1 integration → R3 sample aggregation → R4 supporting blocks. **Active next path:** D1 description records → D2 concrete accounts → D3 overview/at-a-glance → D4 verification and Brian’s profile review. **Conditional branch:** R2 only for a named blocked statement that survives this use of existing evidence; unsupported points remain unknown. **Optional held follow-up:** R5 quotations. Benchmarks, broader collection and stability claims are outside this sequence.

Brian’s bounded V4 generation and Codex’s artifact review are complete. Brian’s product feedback requests richer, human-friendly descriptions. D1–D4 are now implemented using existing evidence. Brian’s bounded V5 generation and Codex’s artifact/wording inspection are complete. Brian’s feedback is “Getting better”; S1 V1 failed the portrait requirement and was reviewed; retain V5. Brian approved the specific required-portrait correction, now implemented as V2, and runs the next bounded validation; do not equate successful generation with reader acceptance. No provider or data work beyond the explicitly requested S1 editorial run is the default follow-up. R1/R3/R4 ship through the existing loader/ledger/rendering path; no new planning document, global inventory or generic binding experiment is required. R2 remains conditional on demonstrated gaps, and held semantic/provider work stays held.

Use the existing entry points for profile delivery and verification; new user-facing checks must also attach to `pte`:

```bash
pte analysis structure-readiness --segment-view --description --json
pte analysis structure-readiness --segment-view --description --check-only --json
pte analysis structure-readiness --segment-plan --json
```

These commands now target V5; V3/V4 artifacts remain preserved. The JSON receipt identifies the profile version, recordings, reused raw leaf count, explanatory points, withheld descriptions, selected/partial/unknown examples, remaining gaps and pending reader acceptance. Check-only returns the same description fingerprint without writing artifacts. Changed outputs use a new version so earlier profiles remain reproducible. Generated reports/caches/receipts belong in the app base; intentional plan/contracts and curated inputs belong in source control.

Codex implements, prepares exact cases/defaults/commands, interprets results and recommends a next action. Brian runs bounded dataset validation, reviews the concrete result, makes minor edits and decides consequential held choices. No open-ended case selection, JSON authoring or annotation is assigned to him.

## Scope control and stopping rules

1. One active product slice at a time. Every task must name its reader-visible improvement and responsible existing module before adding code or inference.
2. Keep a completed R1/R3/R4 result deliverable even if a conditional R2 gap remains unresolved. Do not let an unsupported desired sentence restart the whole product pipeline.
3. Never treat a contract, synthetic test or bounded feasibility PASS as persisted/admitted evidence for profile 318. Never reinterpret a frozen leaf to obtain a more complete-looking profile.
4. Do not reopen TypeSafe V1/V2, connected extraction, closed collector/discovery panels or exact-span nomination as an implicit next step. A smaller schema, stronger model or another synthetic round is not the active plan. A specific future proposal needs a demonstrated upstream gap and separate user decision.
5. A bounded validation result has a predeclared acceptance/failure decision. If it fails, record the failure, preserve the usable profile, and present the smallest concrete decision; do not automatically change prompts, thresholds, models or sample size.
6. Run focused tests and inexpensive checks only; no large fixture/corpus evaluation or monitoring. Brian executes dataset commands. Validate eligibility/provenance, conservative aggregation and point/block linkage. Optional quote tests must also prove analytical output is unchanged by absent/rejected quotations.
7. Only Brian’s explicitly requested bounded S1 editorial run is prepared for execution. No other provider/model calls, broader collection, changed measurement/admission rules, production activation, benchmark similarity/ranking, pastor score, ministry-wide stability claim or Ollama quotation execution is authorized here.

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
