# Current product plan: readable pastor profile with evidence underneath

**Brian's accepted direction, 2026-10-19.** Build a human-readable, evidence-backed pastor description first, then work backward to the observations, interpretation rules and code needed to produce it. The first implementation should deliver a working descriptive profile with an embedded three-sermon example, traceable claims and explicit gaps. It is not a blank template, a new measurement target, an approved theology assessment or authorization to execute a model.

The companion [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) defines the code changes, milestones and acceptance checks. The two documents are the active product/engineering pair; the worked example is part of implementation, not a separate preliminary document.

This product plan builds on [segment evidence first, illustrative quotations last](SEGMENT_EVIDENCE_PLAN.md). Its minute-based processing and downstream Ollama quotation policy remain. The current [read-only evidence view](review-proposals/segment-profile-view-v1/REVIEW.md) becomes the lower evidence layer rather than the entire product. Earlier exact-span extraction and collector dead ends remain closed.

## What the reader should see

1. **Readable assessment.** A few concise paragraphs, approximately 250–400 words when the evidence warrants it, explaining the most defensible observations about this sample. Prefer concrete language to probabilities. State the three-sermon scope near the assessment. Attribute supported sample findings without generalizing to a whole ministry. Each substantive clause must link to the observations and source segments that justify it.
2. **Pastor at a glance.** A small dimensional table summarizing what can be characterized responsibly. Initially use supported sample descriptions or explicit unknowns. Do not invent “High/Moderate/Low” bins; qualitative labels require stated interpretation/aggregation rules before automatic display. Missing measurements and low observed values are separate states. There is no single pastor score.
3. **Benchmark comparison, when justified.** Reserve the product section, but leave current comparisons explicitly unavailable. No sample pastor X/Y/Z, nearest-benchmark claim, 78% similarity or numerical rank is supplied as if measured. A future comparison requires compatible benchmark inputs, a defined dimensional method, sampling/coverage rules and evidence that the displayed result means what readers think it means. It remains a separately held implementation/validation decision.
4. **Dimensional analysis.** Organize existing and future information into the four families below. Preserve distinctions between attention, rhetorical treatment, local semantic observations, adopted positions and stable patterns. Do not expose internal taxonomy as an unexplained list of probabilities.
5. **Why PTE says this.** Open a claim or dimension to inspect its measurement meaning, question/model/version, source eligibility and supporting sermons/segments, with full transcript windows and timestamp links. Report contrary, missing, unresolved and below-threshold states where relevant. The current evidence browser supplies this foundation.

The reader's hierarchy is **assessment → at-a-glance → benchmark comparison (currently unavailable) → dimensional analysis → supporting observations → sermons and transcript segments**. Processing still runs in the opposite direction: eligible source segments and cached observations support claims; optional illustrative quotations are selected last. A visually prominent product section does not become an upstream inference prerequisite.

## Four analytical families

| Family | What it answers | Current boundary |
|---|---|---|
| Preaching style | How does the sample use exposition, doctrinal argument, practical application and narrative illustration? | Existing segment treatment probabilities are reusable. Any pastor-level “High” label, style predominance or claim of frequent cross-book exposition needs a defensible rule and evidence; raw probability is not a pastor score. Existing compatible Scripture measurements should be checked before proposing new data. |
| Theological emphasis | What subjects receive meaningful attention? | Use existing topic prominence and source links. A topic being discussed does not establish agreement, adoption or a resolved position. Three sermons do not define ministry-wide priorities. |
| Theological orientation | How is a theological subject actually described, qualified, affirmed or rejected? | Use the nine approved local salvation leaves only within their meanings; three unresolved relationships remain unknown. Bound proposition/voice/polarity distinctions need adequate evidence. Divine initiative and human response can both be emphasized; do not force compatible concepts onto an invented opposing scale. |
| Pastoral/rhetorical orientation | What listener response or relational posture does the preaching express? | Distinguish application/treatment already measured from listener directives or reassurance/warning bindings not established in this sample. Validation of a question elsewhere does not populate this profile. No new certainty/exploratory or individual/communal dimension is assumed ready. |

Names and boundaries are a product organization, not new measurement contracts. A dimension can be discussed qualitatively where source evidence supports it, but it must not be silently populated by an adjacent topic proxy. Preserve existing G1/G2/G3/A1 semantics and historical scopes; do not reintroduce exact-span nomination as a universal requirement.

## Worked example for the first implementation

Use reviewed profile **318**, its three current member recordings **4589 / 281 / 3973**, and the [compatible cached inventory](review-proposals/segment-cache-inventory-v1/REVIEW.md): 158 topic/treatment blocks and 33 routed salvation blocks. Video titles name John Bradshaw, while the reviewed profile currently lacks a display label. Preserve that distinction in the prototype and record identity labeling as a metadata gap rather than silently creating a new accepted name. The materials are already used development/review evidence, not a new confirmation set.

Deliver the following together within [implementation milestones 1–3](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md#milestone-1--implement-the-descriptive-profile-contract-and-worked-example):

- **A complete, human-readable profile draft.** Populate the proposed sections to the extent supported by these recordings. Use unavailable placeholders for comparison and unsupported conclusions. The supplied example prose is an aspirational product example, not accepted wording: claims such as strongly Bible-centered, frequent cross-book argument, direct appeals or stability must be independently substantiated, narrowed or withheld.
- **A claim ledger.** For each substantive clause, record the proposed wording, scope, family, support status, exact cached fields/question/model/version and eligible sermon/segment/time/source-hash links. Explain the inference from observations to wording, alternatives/counterevidence and the proposed code responsibility. Segment-level evidence links are sufficient for this step; no quote or minimal utterance extraction is required.
- **An at-a-glance interpretation slate.** Define which descriptions are already supportable, which aggregation/interpretation rules are merely proposed and which dimensions remain unmeasured. Do not convert .85 model probability to 85/100 or to an automatic “High.” Do not introduce a new cutoff to make the sample read well.
- **A prioritized gap ledger.** Every desired unsupported sentence/field gets a precise cause, existing reuse options, smallest remedy, impact on the reader and an implementation-versus-data distinction. Do not assume that five or ten new measurements are needed; let the draft reveal which gaps matter.
- **A code-backward map.** Separate deterministic reuse/eligibility/link assembly, proposed descriptive aggregation or wording rules, genuinely missing semantic distinctions and insufficient sampling. Describe the smallest implementation that could reproduce the supported draft without altering frozen raw results. The draft is a reviewable product example, not ground truth that future measurements must be tuned to match.

No source or profile-wide aggregation rule is implemented by this plan. Produce the worked draft alongside the first code, schema and screen; do not add a standalone draft-approval gate before implementation. No draft is written or accepted here. Completing it may expose an unknown field rather than a useful sentence, which is a valid outcome.

## Gap classification and priority

| Gap class | Example | Preferred next response |
|---|---|---|
| Existing evidence not exposed | Compatible Scripture or segment observations exist but the view does not use them | Reuse/assemble before collecting anything. |
| Interpretation or aggregation missing | Local application judgments exist, but “application-oriented” has no defined sample-level rule | Propose a transparent interpretation and review it against source evidence; do not invent a quality score. |
| Semantic distinction missing | Topic attention cannot distinguish a quoted view from an adopted position | Leave the claim unknown; identify the precise needed distinction and compatible existing contracts first. |
| Sampling insufficient | Three correlated recordings cannot establish long-term stability | State the sample scope. New independent coverage needs separate collection authorization. |
| Identity/metadata missing | Titles name a pastor but the reviewed profile has no accepted label | Prepare the existing provenance for a bounded metadata decision; do not infer identity from prose alone. |
| Comparability/calibration absent | A proposed “78% similar” has no established interpretation | Leave comparison unavailable and specify the missing method/validation. |
| Presentation only | A supported point needs an illustrative quotation | Use the downstream Ollama quote stage later; no new analytical measurement is implied. |

Prioritize by how much a gap changes the reader's useful understanding, whether existing evidence resolves it, the risk of unsupported wording and the smallest remedy. Missing peripheral dimensions need not block the initial profile. Missing evidence must not silently disappear from similarity calculations: any future result needs declared comparable dimensions, overlap, exclusions and limits. Reporting “8 of 11 comparable dimensions” is useful coverage disclosure, but does not validate a similarity percentage or make comparisons over differing subsets interchangeable.

## Illustrative quotations remain last

After a point is established and a strongest supporting segment is chosen, configured Ollama may receive the complete CENTER minute plus eligible BEFORE/AFTER minutes, distinctly labeled. The excerpt's substantive content must come from CENTER; neighbors contribute only necessary continuation, conditions, qualifications, attribution or recipient identity. Use actual adjacent pipeline blocks and their real bounds, not arbitrary exact-minute cuts. Preserve same-source version, eligibility and literal source order; withhold if faithful support is unavailable.

Choose one contiguous verbatim excerpt; no paraphrase, silent stitching, invented words or neighboring-only quote. Verify it deterministically against the source and preserve speaker/reporting scope. Repeated text with ambiguous location remains unresolved. Quotes neither create analytical authority nor fix an unsupported claim. No quotation is required to support the profile draft's construction, and no quote request/model/runtime is prepared by this update.

## Current status and authorization

**Done:** minute/segment evidence lineage and context work; existing compatible topic/treatment/salvation inventory; a working read-only three-sermon evidence view; retirement of the upstream exact-span detour.

**Next implementation proposal:** [milestones 1–3](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md#delivery-order-and-current-authorization) as one bounded provider-free feature: description contract, evidence-to-wording rules, embedded worked example, readable screen, claim links, explicit unknowns, tests and the consequential gap map. Brian reviews a working result rather than a blank template or another standalone planning exercise.

**Held:** new model/provider calls, broader collection, production activation, new automatic provenance/adoption rules, changing frozen measurements/thresholds, implementing new profile aggregation/scoring or comparison/ranking, recurrence/stability claims and Ollama quote execution. This user request authorizes plan updates only; it does not execute the implementation milestones or implement the proposed rules. Existing approved descriptive projections and raw observations are retained, not invalidated or enlarged in meaning.

See the [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) for delivery order, files to reuse and acceptance criteria.

Current plan check:

```bash
pte analysis structure-readiness --segment-plan --json
```

The original [segment-first plan](SEGMENT_EVIDENCE_PLAN.md), closed experiment packets, accepted semantics and all raw receipts remain preserved as historical/supporting evidence. Use the [current status index](review-proposals/README.md) and current registry rather than earlier next-step recommendations.
