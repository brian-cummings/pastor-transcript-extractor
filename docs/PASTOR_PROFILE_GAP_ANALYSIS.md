# Desired pastor characteristics and measurement gaps

This is the desired-characteristic and semantic-fit specification, not an execution plan. Use the [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) and [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) for current acceptance, measured progress and next actions. The 59-signal registry defines existing measurement meanings; the C01–C20/D01–D06 catalog defines desired reader questions. Semantic fit does not establish validated observations, production admission or numerical comparison readiness.

## Desired profile, before considering available measurements

The product should answer: **What does this pastor teach, how do they interpret
and address people, and what makes their teaching distinctive or noteworthy within
a stated corpus and landscape?** It should answer with evidence, qualified claims,
unknowns and variation, not a single ideological or quality label.

The desired profile has five complementary areas:

1. **Teaching content and positions.** What propositions are affirmed, rejected,
   qualified or left open? How are God, Christ, the Spirit, Scripture, human nature,
   sin, salvation, discipleship, church, mission, ethics, creation, suffering,
   public life and final destiny understood? A topic receives a position field
   even if the current detector can measure only attention to it. Salvation includes
   divine action and human reception, saving benefits, assurance, conduct, and their
   relationships; it is not just frequency of salvation vocabulary.
2. **Attention and treatment.** Which subjects organize the teaching, receive
   recurrent attention, or appear only occasionally? How does the pastor explain,
   reason, narrate, apply, exhort, and use material? What are listeners asked to do?
   These characteristics can differ between pastors who affirm similar positions.
3. **Interpretation and Scriptural engagement.** Which texts are used, what role
   do they play in claims, and what interpretive operations are demonstrated?
   Distinguish citation, reading/retelling, explanation, argument from a text,
   canonical connections, and application grounded in the passage. A profile
   should show scope and variation without assuming that more references means
   better interpretation.
4. **Pastoral address and developed teaching.** How does the pastor respond to
   suffering, vulnerability, doubt, disagreement and moral failure? What explanation,
   qualifications, reasoning, acknowledged tensions and concrete care/application
   are provided? Describe observed posture and development; do not infer private
   motives, empathy as an inner feeling, intellectual ability or listener outcomes.
5. **Relations and variation.** How do propositions fit together? Which treatments
   and positions recur, vary by circumstance, or change over time? What is broad,
   deep, coherent or inconsistent within a named subject and scope? These are
   questions about structured evidence, not averages over unrelated leaves.

An incomplete profile is valid, but its missing fields must be visible against
this desired specification. An archive of safe occurrence statements is an initial
view of the profile, not the completed product.

### Desired characteristic contract

Each desired characteristic requires an ID, a human question, why it matters for
description/comparison/discovery, and its own target pastor statement. It also
requires the sermon-observation prerequisites that would make that statement
possible, its representation, coverage/opportunities, qualifications and conditions
for non-characterization. The desired statement is defined **before** selecting
supporting leaves; an existing narrow leaf statement cannot replace it.

```text
desired_characteristic_id, question, product_value, target_statement
semantic_kind, typed_value_shape, scope_and_conditions
required_sermon_observables, required_evidence_granularity
current_supporting_contract_ids, other_existing_evidence_sources
measurement_fit: fully | partially | not_measurable
missing_information, gap_type[], proposed_resolution
new_measurement: no | extend_or_bind_existing_evidence | yes | conditional
projection_requirements, readiness_and_abstention, priority
```

`measurement_fit` is semantic fit under sufficiently good and sufficiently broad
collection, not today's approval or sample size. `fully` means the current observable
kinds could answer the characteristic as narrowly defined; it does not override
any registry gate. `partially` means some intended meaning is absent. `not_measurable`
means the defining information is missing, even if current leaves can find passages
to inspect. Collection accuracy, identity, coverage and projection readiness are
separate axes. A million accurately scored paragraphs do not make an incomplete
observable semantically complete.

Gap types are: **observation** (information not collected), **binding** (known
signals not related to a proposition/object/text), **projection** (aggregation or
sufficiency), **coverage** (routing/sample/independence), **validation** (observable
not yet reliable), and **comparison** (cohort/encoding/weights). Several may apply.
A binding gap can require a new semantic observation even when source passages
already exist; it is not always fixable by a join on overlapping timestamps.

The profile uses the same structured characteristic and evidence records for
human description and quantitative analysis. Position records preserve proposition,
polarity, conditions and mixed/time-specific findings. Numeric treatment/attention
summaries name their estimands. Developed-teaching rubrics retain separate facets
and representative/counterevidence. Prose-only characteristics remain useful without
being forced into a clustering vector. Corpus coverage remains visible everywhere.

## Desired characteristic → current evidence matrix

The desired IDs below describe product questions, not new taxonomy leaves. `T`,
`S`, `L`, `P`, `M`, and `H` refer to the namespaces in the existing registry.
Where “all” is used, it means the finite canonical family, not unspecified new leaves.
None of these rows approves a new measurement pack.

| Desired characteristic / why useful | Current supporting leaves or other evidence | Fit | Missing information and gap types | New measurement needed? / proposed resolution |
| --- | --- | --- | --- | --- |
| **C01 Topic emphasis:** what subjects organize this pastor's teaching? Supports characterization and emphasis comparison. | All 20 `T:*` prominence signals. | Fully for measured topic-attention pattern. | Projection, coverage: whole-sermon validity, equal-sermon estimand, series/time sensitivity and reference basis. | **No** for this narrow characteristic. Specify projection and coverage, retaining overlap; do not infer positions. |
| **C02 Salvation benefits and expressed relationships:** how does the pastor present saving action, reception and experience? Supports an intelligible salvation account. | All 12 `S:*`, with nine usable and three unresolved; `T:salvation_gospel` supplies attention context only. | Partially; substantial support for broad themes and nine explicit relationship types. | Observation/validation/binding: causal direction for the unresolved leaves; detailed mechanisms, qualifications, adopted opposing claims; assurance polarity. | **Yes or extend**, for the missing relationship/position details. Preserve existing nine observations; never call salvation theology as a whole fully covered. |
| **C03 Assurance/security position:** can salvation be known, lost or retained, and under what conditions? Enables real theological comparison. | `S:assurance_security` finds treatment. | Partially for treatment; not measurable as a resolved position. | Observation/binding: proposition, known-versus-permanent distinction, loss/retention polarity, conditions and adoption. | **Yes**: a separately specified bound proposition observation; no threshold on current presence can recover it. |
| **C04 Other theological positions:** what is affirmed about God, Christ, Spirit, Scripture, sin, church, human nature, creation and final destiny? Required for “what does this pastor teach?” beyond salvation. | Relevant `T:*` attention; `H:doctrinal_argument`; `S:judgment_final_destiny` only a broad salvation link. | Partially for finding material; positions largely not measurable. | Observation/binding: affirmative/negative/conditional propositions and relations, not just the subject. No systematic doctrine coverage from 20 topic Scores. | **Yes**, targeted proposition contracts for desired questions; no automatic exhaustive theology tree. Mark unanswered questions as such. |
| **C05 Basic sermon/application style:** which explanatory, argumentative, narrative and practical modes recur? Useful even without quality judgments. | All four `H:*`; all nine `L:*` identify action kinds; all six `M:*` identify material/form. Grounded legacy style spans are a separate possible source. | Fully for the defined basic mode/action/material patterns; not for every possible style. | Projection/coverage/validation: rates and sufficiency; independent evidence linkage; legacy/type-safe compatibility. | **No** new semantic dimensions for basic pattern. Keep distinct modes and denominators; do not substitute them for depth or empathy. |
| **C06 Application development:** does teaching explain how and why to respond, including circumstances, obstacles and concrete steps? Supports noteworthy application discovery. | `H:practical_application`, all `L:*` identify responses, especially `serve`, `change_behavior`, `spiritual_practice`. | Partially. | Observation/binding: action connected to rationale/text, feasible specifics, addressed obstacles, qualified context. Presence of an instruction does not establish developed application. | **Extend/bind**: observe the development around an appeal. Do not score listener success or assume every simple appeal should be elaborate. |
| **C07 Public-life treatment:** how are public affairs reported, illustrated, evaluated or used for mobilization? Describes a distinct teaching tendency. | All eight `P:*`, `T:society_public_life`; `L:civic_action` overlaps with advocacy. | Fully for the defined functions; no ideology implied. | Coverage/projection: eligibility-only routing decision; conditional treatment opportunities; deduplicate shared action evidence. | **No** new function leaves. Resolve routing and projection; actual positions belong to C08. |
| **C08 Public-life positions:** which public propositions/objects are supported, opposed or prescribed, and why? Enables agreement/disagreement comparison. | `P:critical`, `supportive`, `prescriptive`, `theological`, `moral`, `advocative`; `L:civic_action`. | Partially for evaluative/action function; not measurable as object-bound positions. | Binding/observation: object, proposition, adopted voice, polarity, remedy, reasons and qualifications. | **Yes or extend** with grounded object/proposition/voice binding. Different objects can receive different evaluations in one block. |
| **C09 Detected Scripture-use pattern:** which books/passages are explicitly/contextually referenced or closely aligned with quoted text? Useful source context. | Outside the 59: `sermon-basics@4` references/alignments and `profile-scripture-usage` structural features; `M:quotation` is not Scripture-specific. | Fully for the detected reference pattern, not all Scripture use. | Coverage/validation/projection: detection scope, undetected paraphrase, transcript quality, compatible runs and sample. | **No** new semantic leaf for detected references. Reuse existing evidence with limits; never interpret zero detections as low engagement. |
| **C10 Scriptural engagement:** how do biblical texts carry explanation, argument and application? Helps surface sustained and substantive engagement. | `H:exegetical_exposition`, `doctrinal_argument`, `practical_application`; `M:biblical_narrative`; outside-registry references/alignments and grounded style spans. `T:scripture_revelation` is attention to Scripture itself, not engagement. | Partially. | Binding/observation: which textual claim supports which teaching/appeal, explanation scope and sustained episode, text's function versus decoration. | **Extend/bind** evidence and observe textual development. Reuse deterministic anchors; no new citation-count proxy for fidelity or depth. |
| **C11 Interpretive tendencies:** what operations does the pastor demonstrate in reading texts? Supports explainable comparison of methods. | `H:exegetical_exposition`; `T:scripture_revelation` can locate discussion of interpretation; C09 anchors. | Partially for locating interpretation; method not measurable. | Observation/binding: demonstrated context analysis, genre handling, word/argument reasoning, canonical linkage, typological application, relation of explicit method statements to actual use. | **Yes**: bounded operations with exact text/claim links. These are illustrative independent operations, not imposed denominational or ideological labels. |
| **C12 Pastoral posture/empathic address:** how are listeners' suffering, doubt, failure or vulnerability addressed? Distinguishes relational treatment. | `T:suffering_adversity_death`, `relationships_family_interpersonal`, `compassion_generosity_service`; `L:serve`, `repent`, `trust` and `H:practical_application` locate possible passages. | Not measurable as posture; thematic/action presence only. | Observation: acknowledgment of experience, treatment of vulnerability, reassurance/challenge, respect, perspective-taking, contextual qualifications. | **Yes**: observable address acts, anchored to listener circumstance. Describe expression, not private empathy or beneficial outcomes. |
| **C13 Depth of treatment:** how far is a subject explained, differentiated and examined? Surfaces developed teaching in specified subjects. | `H:doctrinal_argument`, `exegetical_exposition`; `T:*` supplies subjects/prominence. | Not measurable as depth; candidate passages only. | Observation/binding: explanatory steps, distinctions, alternatives, qualifications, reasons/evidence and developed implications within an episode. Duration/technical words are not depth. | **Yes**: separate observable development facets with subject/claim links. Keep facets rather than a universal “deep pastor” score; human judgment interprets them. |
| **C14 Articulated theological coherence:** how do claims relate, and are tensions resolved within comparable scopes? Supports meaningful coherence discovery. | Some explicit `S:*` relationships; `H:doctrinal_argument` locates reasoning. | Not measurable as a coherent theological account. | Observation/binding/projection: propositions, conditions and cross-claim relations; contradictions, qualifications and stated reconciliations. Similar prominence and reasoning presence are not logical compatibility. | **Yes plus projection**: grounded claim/relationship graph and bounded tension review. Coherence is not truth or absence of found contradiction. |
| **C15 Topical breadth:** which independent subjects receive developed treatment across the selected corpus? Supports scope comparison/discovery. | All 20 `T:*`. | Fully for breadth within this topic inventory; not theological completeness. | Projection/coverage/comparison: adequate opportunity, corpus/series size, exposure-aware calculation, overlapping categories and detector policy. | **No** new leaf. Derive a transparent topic coverage/distribution with standardization/sensitivity; never sum scores as mutually exclusive proportions. |
| **C16 Scriptural breadth:** which detected canonical areas/passages are used? Distinguishes a different breadth from topic breadth. | Outside-registry detected books/chapters, canonical shares, concentration and reference breadth. | Fully for detected-reference breadth. | Coverage/comparison: count/sample effects, detection limits; reference breadth is not breadth of faithful exposition. | **No** new detection. Reuse named structural estimands and exposure limits; exposition breadth would additionally require C10 binding. |
| **C17 Measured-pattern consistency:** do emphasis, appeals and treatments recur across independent series/periods? Supports stable characterization. | Applicable `T`, `L`, `P`, `M`, `H`, nine usable `S`; metadata and existing sensitivity diagnostics. | Fully in observable type; not yet projected/approved for the intended stable claim. | Projection/coverage: recurrence rules, independent series/period support, dates, duplicate handling and sensitivity. | **No** new semantic leaf for these patterns. Define feature-specific sufficiency and preserve variation. Stability is not correctness or belief consistency. |
| **C18 Position consistency/change:** are the same qualified propositions affirmed over time, mixed, or changed? Needed for reliable positions and human comparison. | Narrow usable `S:*` positive relationships; remaining families mostly locate material. | Partially. | Observation/binding/coverage/projection: explicit opposing/conditional claims and objects, dates, reasons, independent repetitions. | **Yes or extend**, reusing bound proposition evidence from C02–C04/C08; temporal projection alone cannot recover missing polarity. |
| **C19 Material and authority use:** what material carries teaching, and when is it treated as authoritative, illustrative or rejected? Describes sources and interpretive posture. | All six `M:*`, `H:doctrinal_argument`, `T:scripture_revelation`, `adventist_doctrine_identity`. | Fully for defined material/form use; partially for authority/adoption. | Binding/observation: source identity, attribution, adopted claim, source's evidential/authority role; rejected quotations remain material. | **No** new leaves for basic use; **extend/bind** for authority function. Do not infer affiliation or truth. |
| **C20 Qualifications and expressed uncertainty:** where does the pastor acknowledge limits, alternatives or unresolved questions? Helps profile precision and posture. | No direct leaf; `H:doctrinal_argument` may locate alternatives but does not identify epistemic stance. | Not measurable. | Observation/binding: explicit uncertainty, qualification or acknowledged alternative tied to a claim; distinguish pastor uncertainty from model/profile uncertainty. | **Yes**, likely within the bound proposition/qualification contract rather than an isolated “uncertain pastor” scale. |

The coverage verdict is therefore mixed. Basic emphasis, finite style/function
patterns, action requests and detected-source patterns are well supported in
observable type. Richer positions and ways of treating people/texts are not covered
by accumulating more presence observations. Salvation is strong in thematic and
some relational support, but detailed theology is still partial. Basic sermon style
is substantially covered; developed treatment is a distinct requirement.

## Landscape constructs derived from the desired profile

These should not become new sermon questions. They compare or relate meaningful
profile characteristics after the relevant evidence and use gates are satisfied.

| Construct / why useful | Inputs and current support | Fit and missing prerequisites | New measurement? |
| --- | --- | --- | --- |
| **D01 Agreement/difference** | Matched C01–C20 characteristics; current registry supports future attention/treatment comparisons more than position agreement. | Partially supportable. Need qualified propositions for belief comparison; shared semantic versions/scopes and per-characteristic uncertainty. | No comparative leaf; underlying position gaps still require observations. |
| **D02 Distinctiveness** | A pastor's supported positions/patterns relative to a declared comparable cohort. Existing basic-pattern leaves provide possible dimensions. | Potentially derivable; comparison, reference population, reliability and sensitivity are missing. Small archive rarity is not broad rarity. | No “distinctive sermon/pastor” detector. Use transparent dimension contributions. |
| **D03 Natural groups** | Meaningful C characteristics, chosen independently of clustering utility, with typed encodings and missingness. | Potentially derivable for adequate shared dimensions; no current clustering approval. Profile gaps restrict what resulting groups mean. | No new leaves merely for cluster separation; never impose ideological axes. |
| **D04 Cluster exemplarity** | Supported membership and distance to a stable group's measured pattern, over adequately shared dimensions. | Not currently available; depends on D03 and coverage. | No exemplar/quality detector. Explain which cluster/dimensions are represented. |
| **D05 Meaningful outlier behavior** | Supported departures in positions, attention, treatment, development or posture. | Potentially derivable; need uncertainty, sample/series checks and dimension-specific explanations. Missing C12–C14 cannot be replaced by citation/style counts. | No outlier leaf; resolve input gaps for the requested lens. |
| **D06 Noteworthy candidates** | Separate C10/C12/C13/C14/C15/C17 and D02/D04/D05 lenses. | Partially supportable as a future product. Depth, coherence and posture are missing; breadth/basic patterns can become inputs after their gates. | No single quality score. Cards contain reason, scope, evidence, counterevidence and limitations; final judgment remains human. |

## Producer responsibilities

Bound propositions need their object, polarity, speaker, adoption, attached conditions and qualifications at the existing category-leaf/shared binding producer. Topic attention or literal quotation cannot supply these distinctions. Reuse compatible constituent observations first.

Text/argument/application relations require eligible endpoints and source support for the relation; co-location alone is insufficient. Observable pastoral address requires act, recipient, voiced frame and relevant restrictions. Neither invitation nor narrated care proves listener uptake, private empathy or enduring pastoral posture.

Coherence/tension interpretations must reuse qualified propositions and relations, retain scope and counterevidence, and provide an explicit warrant. End-stage profiles cannot fill missing local meanings from raw text.

The [current implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) defines the next bounded response/qualification checkpoint, its inspected evidence and acceptance. The desired catalog does not activate another G1/G2/G3 collector, model variant, broad corpus run or scoring experiment.
