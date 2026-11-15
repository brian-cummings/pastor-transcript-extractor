# Pastor profile product plan

**Current authority: 2026-11-01.** Read with the [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md), [current handoff](HANDOFF.md) and [status index](review-proposals/README.md). These replace earlier next-step instructions. [AGENTS.md](../AGENTS.md) governs evidence reuse and producer responsibility. The historical goal-tool closure and bounded pilot PASS do not mean the product goal has been achieved.

## Goal and present position

Deliver useful, automatically assembled, source-grounded pastor analysis **and mathematical comparison across explicit dimensions with benchmark pastors**. The same qualified upstream evidence should support the readable explanation and the numerical comparison. Show what a pastor teaches, how the sample develops and addresses it, what remains unknown, and which supported dimensions account for similarities and differences.

## Full analytical scope

The finished profile covers **all** of the areas below, not only salvation. The current salvation/response work is the first bounded slice, chosen to prove the evidence path; it does not narrow the product. Characteristic IDs refer to the desired catalog in the [gap analysis](PASTOR_PROFILE_GAP_ANALYSIS.md), which owns each characteristic's target statement, measurement fit and gap types.

| Area | What the reader should learn | Catalog IDs | Present state |
|---|---|---|---|
| Theological positions | What is affirmed, rejected, qualified or left open about God, Christ, Spirit, Scripture, human nature, sin, salvation, assurance, discipleship, church, mission, ethics, creation, suffering and final destiny. | C02–C04, C14, C18, C20 | Salvation thematic/relational evidence partial; active bounded slice. Complete adopted positions not yet qualified. Other doctrines not started as positions. |
| **Public life and political views** | How the pastor treats public affairs (reported, illustrative, theological/moral framing, critical, supportive, policy prescription, civic mobilization) **and** which positions on specific public issues, policies, institutions or figures they support, oppose or prescribe, with reasons and qualifications. | C07 treatment, C08 positions, `L:civic_action` | C07 eight-question treatment pack: readiness PASS; eligibility-only routing awaits review ([contract](PUBLIC_LIFE_TREATMENT_BEHAVIOR_CONTRACT.md)). C08 needs issue-bound proposition/voice/polarity binding, the same producer gap as salvation positions. |
| Topic attention and breadth | Which subjects organize the teaching, recur, or appear only occasionally. | C01, C15 | Cached topic projections implemented. Attention is not belief. |
| Preaching style and application | How the pastor explains, reasons, narrates, applies and exhorts; what listeners are asked to do; how applications are developed. | C05, C06, C13 | Basic style and listener directives substantially covered in observable type; developed treatment/depth not yet measured. |
| Scripture use and interpretation | Which texts are used, what role they play, and which interpretive operations are demonstrated. | C09–C11, C16 | Scripture-use measurements and benchmark implemented; engagement and interpretive tendencies partial. |
| Pastoral address | How the pastor responds to suffering, doubt, disagreement and moral failure; reassurance and challenge. | C12 | Not yet qualified; no nonempty address inventory. |
| Sources and authorities | Use of other material and authorities. | C19 | See gap analysis. |
| Consistency and variation | Which patterns and positions recur, vary by circumstance or change over time. | C17, C18 | Requires a declared sample/opportunity contract; not established. |
| Comparison and landscape | Agreement/difference, distinctiveness, natural groups, exemplars, outliers and noteworthy candidates relative to benchmark pastors. | D01–D06 | Only Scripture-use distances exist; all others depend on the characteristics above. |

Political views are measured the same way as theological positions: as specific, source-bound positions with the pastor's own voice, polarity, reasons and qualifications, and treatment functions observed per block. Comparison may report agreement or difference on matched public-life positions and treatments. A reported or quoted claim is not endorsement, public-topic attention is not a stance, and no party, ideology or Christian-nationalism label is inferred from topics, Scripture-use distances or unrelated measurements. The existing Scripture-use benchmark deliberately excludes politics; public-life dimensions enter comparison only through the dimensional acceptance criteria below.

**Status: early working prototype; original useful automatic-analysis goal partially met; broader dimensional benchmark goal not achieved.** No credible completion percentage or delivery estimate has been established.

| Capability | Evidence of progress | Remaining acceptance gap |
|---|---|---|
| Evidence and assembly infrastructure | Compatible saved evidence, source coordinates, provenance, caching, dependency checks, bounded spending, CLI and final-document handoff work in bounded cases. | Technical execution does not establish semantic fidelity or useful pastor-level analysis. |
| Reviewed readable examples | V8/profile 318 and P1/profile 130 are delivered review examples. | V8 includes seven authored interpretations; P1 includes four authored descriptions and three authored interpretations. These do not demonstrate automatic discovery. |
| Automatic section | Profile 318, recordings 281/3973/4589: six discussion-level clauses, 126 reused local relationship rows (29 positive), one qualified growth-timing finding and a limited co-presence interpretation. | All 12 complete experimental bindings and all 12 proposed specific response descriptions remain withheld. Much of the section is broad discussion membership. Response conditions, adopted theology and reassurance/challenge relationships are unresolved. |
| Existing mathematical benchmark | Immutable reviewed reference panels, Scripture-use feature snapshots and descriptive distance comparisons are implemented; see [benchmark workflow](reference-benchmarking.md). | This is a narrower Scripture-use space. It does not validate theological, pastoral or overall preaching similarity; meaningful broader geometry and sample stability remain unestablished. |
| Generalization | Source-linked development outputs and focused integration checks exist. | The six windows are exposed development material. No untouched holdout or validated general automatic profile generator has been demonstrated. |

The November 1 response-and-conditions check failed: final development qualified 0/10 response proposals; unchanged confirmation qualified 0/3, with one proper context abstention. One growth discussion clause released after a citation-inventory fix. The required two specific response findings are absent. The traceable dimension is unknown with null score/rate, and no production admission follows. The configured-base `evaluation/response-conditions-dimension-v1/DELIVERY_318.md` records the bounded failure, $0.134451216 charge and prepared offline next-step proposal.

## Acceptance for useful automatic analysis

1. Produce a concise, substantive explanation of the declared sermon sample, beyond category labels, definitions or citations. The first bounded subject is salvation, personal receiving response and spiritual growth, including reassurance/challenge where supported.
2. Require no human-authored pastor readings, portrait prose or pastor-specific connective warrants at runtime. Generic contracts/templates are allowed. Evaluation readings cannot become runtime evidence.
3. Reuse compatible saved observations, individual leaf/refinement/composed answers and reviewed bindings first. Check source/context, meaning, model/provenance, eligibility and policy; a whole-pack miss is not global absence.
4. Capture requested/described response, attached conditions/qualifications, gradual growth versus immediate perfection, voiced speaker, preacher adoption and proposition polarity at the existing responsible leaf/shared producer. End-stage prose consumes these distinctions.
5. Preserve source coordinates, evidence/premise IDs, scope, attribution, polarity, meaning-changing qualifications and counterevidence through aggregation and into the readable section.
6. Give interpretations explicit warrants, alternatives, defeaters and dependencies. Priority, dominance, frequency and causal claims need specific warrants. Co-presence alone establishes none of them.
7. Expose omissions, unsupported dimensions and coverage limits. Topic attention is not belief; invitation is not listener uptake; local speech is not a stable temperament or complete theology.
8. Exercise ordinary shared `pte` assembly, analysis support and final-document input with source links. Preserve V8/P1 behavior and established semantics; avoid a second general-purpose theological extractor.
9. Assess original outputs unchanged for fidelity, qualifications, omissions, counterevidence, usefulness and coverage separately. Mechanical success and model approval are separate from semantic acceptance. Preserve the known main-question false acceptance as a regression.

## Acceptance for dimensional benchmark comparison

1. **Shared contracts:** Candidate and benchmark pastors use the same versioned dimensions, meanings, eligibility rules and scoring/aggregation rules. Retain the four families: preaching style, theological emphasis, theological orientation and pastoral/rhetorical orientation, and add **public-life treatment and positions (political views)** as a comparison family once qualified public-life dimensions exist. The current presentation code (`profile_description.py`) still renders only the four original families for the V8/P1 regression examples; extending it is part of delivering public-life dimensions, not a change to those examples. Reuse the narrower Scripture-use implementation where compatible.
2. **Defensible measurements:** Distinguish mention, description, endorsement and condition where needed. Define each dimension's target statement, units/scale, denominator or opportunities, aggregation, exclusions and non-characterization rules before assigning values. Model probabilities are not pastor scores.
3. **Traceable values:** Each value retains contributing observations, source links, qualifications, exact sample, producer/model versions and calculation. Authored portraits and presumed benchmark identities are not measurement ground truth.
4. **Comparable samples:** Declare sermon selection, time/topic coverage, sample size and dependence. Account for overlapping blocks, repeated material and unequal opportunities. Do not infer ministry-wide traits from a selected development sample.
5. **Missingness and uncertainty:** Unknown is not zero, negative evidence or agreement. Retain measurement uncertainty and sampling limitations separately; abstain when evidence or comparability is insufficient. Do not label uncalibrated uncertainty as calibrated confidence.
6. **Interpretable mathematics:** Report per-dimension differences first. Any aggregate distance/similarity needs explicit normalization, feature-family treatment, weights, missing-value policy and sensitivity checks. No overall quality, ideological or church-fit score is implied. Broader dimensions need not be forced into an unjustified scalar.
7. **Benchmark integrity:** Reference membership is reviewed and versioned. Use identical evidence requirements for candidate and references; preserve immutable panel snapshots and input lineage. A well-known theological identity cannot fill a missing value.
8. **Validation:** On independent material, check fidelity of measurements and whether the comparisons reflect supported differences. Check stability under reasonable sample and weight changes, and report failures/abstentions. A plausible nearest neighbor is not validation.
9. **Reader explanation:** Show which dimensions drive a result, with evidence, coverage, uncertainty and contrary examples. Numerical comparison and readable analysis must agree on the underlying meanings.

## Reader experience

Lead with a readable assessment and at-a-glance dimensions, then eligible benchmark comparisons and the analytical families (including public life and political views, shown as unavailable until qualified), followed by warrants, observations, sermons and source navigation. Unsupported comparison stays visibly unavailable. A shorter faithful account is preferable to imitation of the Henry Johnson example; do not optimize toward an authored reference portrait.

## Scope and authority

**2026-11-15:** Brian approved the [bound-claim pilot](BOUND_CLAIM_PILOT.md) as the active sequence. It tests the extraction mechanism (DeepSeek V4 Pro producer, Jev verifier, calibrated gates) on ten sermons under a $5 ceiling with five fixed acceptance criteria. The November 1 objective below is closed history.

The active November 1 objective is one faithful response-and-conditions dimension through the existing workflow: six exposed development windows and at most four independently coordinate-selected additional existing windows for profile 318. Confirmation coordinates are frozen before producer revision and retain exposure disclosure. Require useful specific findings, attached qualifications, unchanged confirmation evaluation and a traceable sample record. No broad benchmark comparison is claimed.

This objective provides a fresh $5 external-provider ceiling, superseding unused earlier credit. Historical budgets and receipts remain unchanged. Reserve at most $0.50 per batch including bounded recovery; unresolved usage retains its full reservation. At most three documented semantic revisions may address demonstrated development failures. Freeze implementation before confirmation results; do not tune against confirmation.

The first concrete dispatch was blocked by automatic approval review. After the explicit payload/provider request, Brian instructed Codex to pursue the goal and the frozen checks resumed. Revision 1 ran the six development windows: all twelve response descriptions remained withheld, with one qualified growth value. A citation-inventory bug prevented ordinary support release; the deterministic fix preserves original failures and charges. The first completed sequence charged $0.079089044 of the fresh $5; later targeted work shares the same ledger.

Revision 2 addresses only two demonstrated producer boundary omissions (surrounding command/application and qualified performed prayer), retaining the other four original requests/answers and valid uncertainty. No model, threshold or checker-meaning change. Confirmation was executed and assessed unchanged after implementation lock; no response qualified. No further agreement-seeking variant is launched. See the [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) for the single sequence and exit criteria.

Keep legacy quarantine, admission and quotation-execution holds. No model switch, threshold tuning, new recordings, broad corpus evaluation or automatic successor experiment follows from this roadmap. Keep relevant source evidence and receipts; obsolete planning text belongs in Git, not additional working-tree snapshots. The [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) names the next concrete checkpoint and later milestones.
