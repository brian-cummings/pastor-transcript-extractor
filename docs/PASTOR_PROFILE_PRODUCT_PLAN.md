# Current product plan: readable pastor profile with evidence underneath

**Brian's accepted direction, 2026-10-19; implementation status updated 2026-10-20.** Build a human-readable, evidence-backed pastor description first, then work backward to the observations, interpretation rules and code needed to produce it. The first implementation should deliver a working descriptive profile with an embedded three-sermon example, traceable claims and explicit gaps. It is not a blank template, a new measurement target, an approved theology assessment or authorization to execute a model.

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

The bounded implementation now provides the worked draft alongside the code, schema and screen. No source or profile-wide aggregation/scoring rule has been added. Brian’s acceptance of the draft and its proposed wording rules is pending. Unsupported fields remain visibly unknown; the draft is not measurement ground truth.

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

**Done:** the evidence foundation plus provider-free implementation milestones 1–3: versioned descriptive record, worked profile 318, deterministic wording rules, readable screen, at-a-glance table, claim/source navigation, explicit unknowns and Markdown/JSON outputs. The milestone 4 consequential-gap/code map is delivered. Current verification passed 40 focused profile tests, plan checks and browser checks; see the [implementation status and next action](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md#delivery-status--2026-10-20).

**Revision following Brian’s review:** the reader-first V2 presentation synthesizes the existing sample, uses titles and clearly qualified name metadata, consolidates salvation themes, adds four exact-source style illustrations, and hides implementation vocabulary behind Technical details. Raw observations and their meanings are unchanged. V1 is not recorded as product-accepted.

**Latest feedback:** Brian recognizes the V2 product-language pass as successful and asks which missing capability would most improve evaluation. V3 makes the small repetition/faith-wording corrections and delivers a prepared decision brief. No further general language-polishing cycle is proposed.

**Source-review pilot executed:** Brian authorized the three prepared passages to test faithful theological proposition binding, with assurance explicitly the test domain rather than the capability. The result contains ten concrete proposed readings with exact field evidence, separate voices/adoption, qualifications, unresolved fields and withheld conclusions. G1’s unchanged proof contract is a partial fit for the general capability; the report identifies predicate, projected-speech, qualification and evaluation-target gaps without extending it. The profile’s own adopted-position fields remain unpopulated.

**Reusable binding implemented:** the same ten source-reviewed readings now retain their theological meaning independently of the assurance predicate inventory. A separate adapter preserves all ten original G1 interpretations unchanged. Compatible G2 evidence/development and G3 invitation/address distinctions are reused; discourse-supported adoption, projected speech and nonconditional qualifications remain explicit. Review with `pte analysis profile-proposition-review --json`; source freshness without writes uses `--check-only`. See the [delivered increment](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md#active-increment--reusable-proposition-binding-separated-from-assurance) and [workflow, verification and limits](PROFILE_PROPOSITION_BINDING.md). Brian’s next action is review of the concrete updated readings; Codex owns feedback interpretation. These remain proposed local source readings, not automatic binding or pastor-wide theological positions.

**Automatic development run completed:** Brian directly approved the same three passages/context. Fifteen TypeSafe requests produced 24 candidates; source-inspected comparison covers all ten development references and twelve field groups. Six readings have matching proposition content, one is partial and three are missing; none is faithful across all reviewed fields. The decision is **do not expand validation yet**: first repair outer/inner speech framing and attribution/evidence selection. The readable discrepancy packet is available through `pte analysis profile-binding-development --json`, with write-free `--check-only`; see [actual results and next remedy](PROFILE_BINDING_DEVELOPMENT.md). The original reviewed readings/assurance interpretations/profile remain unchanged. No generated record is accepted or projected.

**Held:** model/provider calls outside that bounded development scope, broader collection, production activation, new automatic provenance/adoption rules, changing frozen measurements/thresholds, implementing new profile aggregation/scoring or comparison/ranking, recurrence/stability claims and Ollama quote execution. Brian authorized the bounded provider-free feature, which is now implemented. This does not authorize execution of any held work or accept the proposed descriptive rules as new semantic admission authority. Existing approved descriptive projections and raw observations are retained, not invalidated or enlarged in meaning.

See the [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) for delivery order, files to reuse and acceptance criteria.

Current plan check:

```bash
pte analysis structure-readiness --segment-plan --json
```

The original [segment-first plan](SEGMENT_EVIDENCE_PLAN.md), closed experiment packets, accepted semantics and all raw receipts remain preserved as historical/supporting evidence. Use the [current status index](review-proposals/README.md) and current registry rather than earlier next-step recommendations.
