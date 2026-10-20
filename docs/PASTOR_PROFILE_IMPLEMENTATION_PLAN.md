# Pastor profile implementation plan

**Current implementation status, 2026-10-20.** Implements the [pastor profile product plan](PASTOR_PROFILE_PRODUCT_PLAN.md). The product plan defines what the reader should receive; this document defines the code, delivery sequence and acceptance checks. These are the two active planning documents. Older implementation sequences are superseded, with historical measurements and decisions preserved.

Brian authorized milestones 1–3 as one bounded provider-free feature on 2026-10-20. They are now implemented and committed; the worked profile and milestone 4 consequential-gap map are delivered. **Brian’s latest feedback recognizes V2’s product-language pass as successful. The next decision is the prepared assurance-position review; no new semantic capability is authorized.** This is implementation completion, not acceptance of new theological measurements, production activation or authorization to cross any held boundary.

## Delivery status — 2026-10-20

| Milestone | Status | Delivered evidence |
|---|---|---|
| 1: description contract and worked example | Implemented; human acceptance pending | `profile_description.py`; versioned profile 318 assessment, at-a-glance table, 24 unchanged underlying claims plus a synthesized reader layer, source identity and explicit unknowns. |
| 2: evidence-to-description rules | Implemented; wording rules proposed for review | Deterministic per-recording topic summaries; local nine-leaf salvation observations; treatment maxima remain inspection candidates. Four exact-source inspection descriptions now support local style examples; they do not establish predominance. Raw meanings and thresholds are unchanged. |
| 3: read-only profile screen and CLI | Implemented; human acceptance pending | `--segment-view --description`, including `--check-only`; HTML, Markdown, JSON and review receipts; bidirectional claim/source navigation and recording filters. |
| 4: consequential gaps | Gap/code map delivered; remedies not implemented | Eight prioritized gaps: adoption, Scripture/cross-book reasoning, pastoral posture, style predominance, sampling, identity, benchmark comparison and quotations. |
| 5: Ollama quotations | Held | No quote selection, runtime preparation or execution. |
| 6: benchmark comparison and stable tendencies | Held | No comparisons, ranking, profile score or ministry-wide stability claim. |

Implementation commits: `780afe6`, `64d7209`, `639a354`. Verification: **25 focused tests passed** (13 description, 5 evidence view, 7 cache inventory), `git diff --check` passed, and browser checks passed for claim disclosure, source windows, reverse navigation, filters and recovery of filtered evidence. There were zero broken internal link targets. No corpus evaluation, provider requests, database writes, new measurements or quotation execution occurred. This verifies the implementation; it does not constitute a new audit of every cached judgment or human product acceptance.

The delivered profile uses recordings **4589 / 281 / 3973**, with **158 eligible topic/treatment blocks** and **33 routed salvation blocks**. Exact-current Scripture-run lookups returned no persisted current run for these recordings. Exact registered leaf-pack paths, including historical refinements and composed answers at those identities, returned no compatible matches. These bounded checks do not establish global absence of older or differently keyed evidence.

The V1 artifacts and their verification receipts remain preserved under the configured base directory. The reader-first revision writes new outputs under `evaluation/pastor-profile-description-v2/`: `index.html`, `profile-v2.md`, `description-v2.json` and `review-v2.json`. The CLI prints the exact immutable output path. See [workflow and interpretation details](PASTOR_PROFILE_DESCRIPTION.md).

### Product-language revision — 2026-10-20

Brian’s review found that V1 exposed internal vocabulary, repeated per-sermon findings and insufficiently answered what kind of preacher the sample suggests. The revision addresses that feedback in the presentation layer:

- A sample-wide assessment and characterization table precede the evidence browser.
- Distinct-sermon membership in existing summaries supports shared/variable topic descriptions and one salvation-theme table. This adds no measurement cutoff, profile score, adopted position or ministry stability claim.
- Four source-inspected treatment passages support concrete local examples. Descriptions are tied to exact source/text hashes, dimensions and timestamps; stale or absent receipts withhold the style wording.
- Sermon titles replace database IDs in the reader layer. Source titles naming John Bradshaw remain explicitly unconfirmed identity metadata.
- Reader descriptions link to understandable explanations and complete passages. Internal states, raw probabilities, IDs, versions and the complete implementation gap map remain behind Technical details disclosures.

The existing observations, underlying claims, source identities, coverage, missing states and unresolved leaves were compared with V1 and are unchanged. The revision is a new reviewable presentation, not an acceptance claim or authorization for a pipeline pass.

Revision commits: `e06c4dc`, `2b12a79`. **33 focused profile tests passed** (13 description, 8 presentation, 5 original evidence view, 7 cache inventory). Browser checks confirmed five at-a-glance rows, nine consolidated salvation themes, zero broken internal links, no flagged machine terms in the initial visible page, working description → explanation → full passage → description navigation, title-based filters, recovery of filtered passages and closed-but-accessible technical provenance. Generation and check-only returned the same description fingerprint.

The concrete V2 review packet is under the configured base directory at `evaluation/pastor-profile-description-v2/f72e06a35af4546f4565ec2d830e8428ec4b91bef698575d2943f8559ac6cea4/`. Review `index.html` or `profile-v2.md`; the complete provenance is in `description-v2.json` and the Markdown/JSON verification receipts. Fifteen synthesized reader claims link to the unchanged evidence ledger. No provider calls, database writes, new measurements, corpus evaluation or quotation execution occurred.

## Current increment — small presentation fixes and a consequential capability decision

The latest feedback explicitly discourages another language-polishing cycle. V3 keeps the successful product structure and makes the requested small changes: terse style descriptors at a glance, concrete examples, sermon-level passage comparisons and nuance in “A closer look,” and “salvation received through faith.” It adds a source-backed next-capability brief, not a new detector or another inventory gate.

**Recommended capability:** proposition-specific theological positions with voice/adoption, polarity, conditions and scope. This most directly changes the useful answer from “which subjects occur?” to “what does the preacher actually teach?” Pastoral tone is the next complementary gap; more style wording, quotations or comparison cannot resolve this missing distinction.

**Smallest first slice:** a provider-free, source-reviewed assurance account on three prepared windows from the existing sample. Reuse G1’s knowability/loss/retention vocabulary and binding fields. Do not infer a permanent-security label, expand G1 to grace/faith/transformation mechanisms, or convert a topic observation into an adopted doctrine. The packet includes two existing assurance observations and one below-threshold contrast. All proposed positions remain withheld, and G1 opportunity status is explicitly unestablished; these are prepared review contrasts, not certified natural positives.

The existing G1 fixed-passage feasibility gate is PASS/closed, with disclosed conservative residuals; discovery and opportunity coverage are unestablished. The prepared targets are not exact matches to that closed pilot’s targets. The V3 source-only discovery review recommends G1 HOLD; A1’s bounded G3 containment decision is not theological adoption authority. No provider, closed-panel replay, G1 V3, collector change, automatic provenance rule, threshold change or broader collection has occurred.

Implementation: `profile_capability_review.py` and exact-source prepared inputs, committed in `15fb892`, `378736b` and `f554359`, alongside the small presentation fixes. The profile and packet are reproducible through the existing CLI:

```bash
pte analysis structure-readiness --segment-view --description --json
```

This writes `index.html`, `profile-v3.md`, `description-v3.json`, `review-v3.json`, and `next-capability-v1.md/json` under the configured base directory at `evaluation/pastor-profile-description-v3/f3ecf29d342b7684399fe6b5449f6e49d5d173c5e5ef2a715f04552f3cc3e9ae/`. Read-only freshness verification remains:

```bash
pte analysis structure-readiness --segment-view --description --check-only --json
```

**Verification:** 40 focused profile tests passed (13 description, 9 presentation, 6 capability packet, 5 original view, 7 inventory). Browser checks verified the shortened glance row, distinct closer-look content, corrected faith wording, the three-case proposal and links to the exact full passages with technical details closed. Internal targets resolve. Generation/check-only fingerprints agree. The underlying observations, source identities, coverage, missing states and original claims remain unchanged from V2.

## Next action — decide on the prepared assurance review

Brian’s bounded decision is whether to approve the provider-free, source-reviewed assurance-position pilot described in `next-capability-v1.md`. The cases, questions, defaults and acceptance criteria are already supplied. Codex owns reading/interpreting the sources and preparing any supported bindings for review; Brian approves/rejects concrete results rather than annotating or designing an experiment.

If approved, the pilot must preserve uncertain or out-of-contract readings and may return withheld positions. Any requirement for a new semantic measurement, provider, automatic binding/admission rule or broader collection comes back as a precise separate decision. This does not reopen a closed G1 experiment or authorize an expanded doctrine catalog. Do not schedule another general language-polishing pass as the next milestone.

## Starting point: what already exists

| Existing component | Reuse in the feature |
|---|---|
| `segment_cache_inventory.py` | Current source hashes, exact question/model/policy compatibility, reviewed membership and missingness; bypass stale materializations rather than infer again. |
| `segment_profile_view.py` | Read-only source loading, eligibility/membership checks, source disclosures, timestamp links and current HTML rendering. Keep its original artifact/version reproducible. |
| `sermon_topics.py`, `sermon_topic_projection.py`, `sermon_topic_profile_analysis.py` | Existing topic meanings, eligibility and persisted per-sermon descriptive measurements. Reuse compatible current values, not stale database projections or invented pastor scores. |
| `sermon_semantic_dimensions.py` | Existing exposition, doctrinal argument, narrative illustration and application meanings. Local probabilities remain local probabilities. |
| `sermon_salvation_relationships.py` | Existing nine-leaf observation policy; preserve unrouted, below-threshold and unresolved states. |
| `profile_analysis.py`, reviewed profile membership and Scripture-analysis artifacts | Verify identity/scope and inspect compatible existing supporting evidence before declaring a data gap. Never substitute upload titles for reviewed identity. |
| Current read-only three-sermon view | Lower evidence layer and initial UI integration point, not the whole end product. |

Initial sample: reviewed profile **318**, recordings **4589 / 281 / 3973**, **158 eligible topic/treatment blocks** and **33 routed salvation blocks**. Source titles name John Bradshaw, but the profile has no accepted display label. The sample is development material, not a representative ministry corpus or a held-out test.

## Milestone 1 — implement the descriptive profile contract and worked example

**Status: implemented; Brian’s acceptance pending.** The requirements below remain the acceptance contract, not unstarted work.

Add a small pure description module, provisionally `profile_description.py`, downstream of the existing read-only evidence loader. Do not add a provider client, repeat localization/classification, replace minute segmentation or require exact utterance geometry.

The versioned description record should contain:

- Profile/source/membership/inventory identity and actual sample coverage.
- Readable assessment composed of identified claims; at-a-glance rows; four analytical families; explicit unavailable benchmark state; evidence and gap links.
- Per-claim wording, family, sample scope, support state, interpretation-rule version and existing observation/sermon/segment/time/source references. Retain raw question/model/version and applicable frozen thresholds separately from display language.
- Per-dimension measured/unknown status and cause; statements being withheld; known counterevidence or uncertainty. Unsupported requested claims do not disappear from the record.
- Explicit separation of source observations, proposed/reviewed interpretations and optional future illustrative quotes. The record confers no new semantic admission authority or validated theological position merely by being typed.

Prepare the actual readable three-sermon profile **inside this implementation milestone**, alongside the schema and code. It is a worked example for exercising the feature, not measurement ground truth. For every desired sentence the evidence cannot establish, narrow it or expose the unknown and record the reason. Do not encode the supplied aspirational prose as a required answer or special-case profile 318's conclusions in production logic.

**Acceptance:** every substantive clause has eligible evidence links or is visibly withheld; scoped local observations do not become ministry-wide claims; missing/unrouted/below-threshold/unresolved states stay distinct; no numerical or qualitative score is invented. The worked example and typed record are inspectable together.

## Milestone 2 — implement evidence-to-description rules

**Status: implemented; Brian’s acceptance pending.** The requirements below remain the acceptance contract, not unstarted work.

Use pure deterministic assembly of existing observations and explicitly described interpretation rules. Prefer source-linked statements about the named recordings before broader characterizations. Make each rule's inputs, wording strength, missing-data behavior and sample scope reviewable. No generative model is required for this first implementation.

Map the product sections as follows:

| Product section | First supported implementation | Preserve as unknown |
|---|---|---|
| Readable assessment | Plain-language statements justified by existing per-sermon topic/treatment/salvation evidence, with expandable claim links | Unsubstantiated “strongly Bible-centered,” frequent cross-book reasoning, affirmed doctrine or long-term stability |
| Pastor at a glance | Concise source-supported sample descriptions with their scope and evidence | High/Moderate/Low until explicit interpretation and aggregation rules are justified |
| Preaching style | Existing four treatment dimensions presented within their meanings | Pastor-wide quality/style predominance inferred directly from a single probability |
| Theological emphasis | Existing per-sermon topic attention and supporting segments | Treating topical attention as agreement or a comprehensive belief system |
| Theological orientation | Existing local salvation observations with qualifications; use independently supported wording only | The three unresolved salvation leaves, new adopted positions and falsely opposing compatible concepts |
| Pastoral/rhetorical orientation | Available application/treatment evidence distinguished from listener-directive or relational-act measurements | Unmeasured directives, reassurance/warning, certainty or individual/communal profiles |
| Benchmark comparison | Explicit “comparison not yet established” state | Nearest benchmark, percentages, ranks, synthetic examples presented as measured results |
| Why PTE says this | Existing evidence browser, source identity, full segments and recording timestamps | Unsupported authority inherited from a quote or a previous fixed-panel witness |

Do not silently pool minutes as independent sermons, map .85 probability to an 85/100 characteristic, invent qualitative bins, or normalize missing dimensions into a flattering result. A supported descriptive sentence may be emitted without a High label. Any new sample-level interpretation rule is versioned and source-reviewed; it does not revise raw measurements, their thresholds or frozen semantic contracts.

Use focused fixture tests for support/withholding boundaries and adverse cases: identical topic with quoted versus adopted material where that distinction matters; source/membership changes; missing evidence; contradictory evidence; below-threshold versus unmeasured; excluded songs/other speakers; duplicate or overlapping segments. Tests should exercise behavior, not merely match the three-sermon draft's wording. Do not run a corpus evaluation or tune measurements to make the draft pass.

**Acceptance:** the rule-to-claim-to-source chain is reproducible; unsupported claims are suppressed with reasons; source changes invalidate derived presentation; existing cached inputs remain unchanged. If a desired sentence needs a semantic distinction the current data lacks, record that gap rather than building an unapproved detector.

## Milestone 3 — deliver the complete read-only profile screen

**Status: implemented; Brian’s acceptance pending.** The requirements below remain the acceptance contract, not unstarted work.

Extend the current renderer with the readable assessment at the top, at-a-glance rows, the four analytical families and an unavailable comparison section. Keep sermon filters, source disclosures and timestamps underneath. Make claim/evidence navigation work in both directions. Keep the three-sermon scope and identity-label uncertainty visible without forcing readers to interpret raw probability tables first.

Use a versioned output artifact, not an overwrite of the original preview or source inventory. Write generated HTML, JSON and review artifacts under the configured application base directory. Keep database/source reads read-only. Reuse the existing `pte` entry point; the implemented extension is `pte analysis structure-readiness --segment-view --description`, with a corresponding `--check-only` path. **The `--description` option is available.** Do not present a standalone script or require Brian to author JSON, choose cases or annotate the corpus.

**Acceptance:** Brian can read an actual supported profile, inspect any claim's evidence, see unknown fields and run the documented CLI. Focused tests and a browser check cover source safety, disclosure/filter navigation, escaping and missing-state presentation. No additional measurement or exact quote is required for this initial feature.

## Milestone 4 — address consequential gaps, reusing existing evidence first

**Status: prioritized gap/code map delivered.** Remedies remain conditional; no held work has been executed.

The implementation delivers a prioritized gap/code map with the actual profile. Separate:

1. Existing evidence not exposed: integrate compatible caches or existing Scripture measurements.
2. Interpretation/aggregation missing: review and implement a transparent descriptive rule; do not create a score by convenience.
3. Semantic distinction missing: specify the smallest necessary distinction and inspect existing approved contracts/answers before proposing another measurement.
4. Sampling insufficient: retain sample scope; additional independent sermons require a separate collection decision.
5. Identity/metadata missing: prepare reviewed provenance for a bounded identity decision, without naming the profile from titles alone.
6. Comparability/calibration absent: comparison remains unavailable.
7. Presentation only: a supported point needs a quotation, not a new analytical judgment.

Prioritize by impact on the reader, available reuse, risk of unsupported wording and the smallest useful remedy. The first screen is not blocked on filling all dimensions or assuming five or ten missing measurements. The earlier 474 exact full-pack cache misses were bounded checks, not proof that all compatible legacy/composed leaf results are absent; inspect applicable reuse paths before any new inference proposal.

**Acceptance:** each consequential gap has a concrete reason and remedy, distinguishing code work from new data/measurement/validation. There is no automatic inference, broader collection, ontology expansion or reopened exact-span experiment.

## Milestone 5 — optional Ollama illustrative quotations, separately authorized

Only after the analytical point and strongest eligible supporting segment are established, implement the product plan's tail-end quote task. Feed the configured Ollama backend complete labeled BEFORE/CENTER/AFTER adjacent segments, preserving actual bounds and source eligibility. Require a contiguous verbatim excerpt with substantive CENTER content; allow neighboring overflow only to complete the same thought or preserve qualifications, attribution and recipient identity. Verify literal source location and retain ambiguity/withholding rather than repairing text or expanding context automatically.

This stage must have its own configured model/digest, prompt/schema, context/output/runtime/review bounds, cache identity and execution decision. No OpenAI replacement, model comparison, TypeSafe quote-selection call, automatic context expansion or upstream minimal-span prerequisite is included. A quote cannot create an analytical claim or alter a measurement.

**Acceptance:** eligible source identity, literal text, center anchoring and scope are verified; unresolved or unsupported excerpts are withheld; profile statements and measurements stay unchanged when quotes are absent. No model execution is authorized by this roadmap.

## Milestone 6 — benchmark comparison and stable tendencies, separately designed

Use comparable dimensions with compatible semantics, reviewed ownership, declared coverage, appropriate sermon/series/period independence and validated interpretation. Define the comparison method and meaning of any percentage before implementation or display. Missing dimensions never silently disappear; coverage such as 8 of 11 dimensions is disclosure, not calibration, and results over differing subsets are not automatically interchangeable.

No nearest-pastor result, similarity percentage, ranking, single pastor score or ministry-wide recurrence claim is planned for the first delivery. Existing analytical-review findings about false closeness, missingness, duplication and sampling remain constraints to resolve for this later milestone, not reasons to restart the old research sequence before the descriptive screen ships.

## Delivery order and current authorization

- **Completed foundation:** compatible inventory and source-linked evidence preview; historical measurement/containment results retain their actual scope.
- **Implemented, acceptance pending:** milestones 1–3 together, plus milestone 4’s gap/code map. Brian’s product-language feedback is recorded as successful; the next action is the prepared bounded assurance-review decision. Codex owns any authorized source interpretation and subsequent recommendations.
- **Later conditional work:** only the consequential gaps Brian approves, then optional quote execution and independently justified comparison. Do not require another inventory/design gate merely to implement the first supported screen.

Brian’s implementation request authorized the bounded provider-free milestones 1–3 and delivery of the consequential-gap map. This status update records their completion; it does not authorize providers, new measurements, collection, production activation, profile aggregation/scoring, comparison/ranking, stability claims or quotation execution. The [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) and this implementation plan are the two active documents; neither turns a historical pilot PASS into general authority.

Verify the active plans and retirement registry with the existing read-only command:

```bash
pte analysis structure-readiness --segment-plan --json
```
