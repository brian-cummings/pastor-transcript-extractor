# Desired PastorProfile and measurement gap analysis V1

Status: **C01–C20 and D01–D06 approved as design direction** by Brian. The next
G1 design is approved and implementation/expansion are explicitly on hold.
[G2/G3 contract designs](review-proposals/g2-g3-v1/REVIEW.md) are now approved
alongside G1. Brian selects a [small G2 feasibility proposal](review-proposals/g2-feasibility-v1/REVIEW.md)
first; its provider/dataset command is prepared but reserved for Brian to run. This defines the desired
product independently of the
existing inventory, then assesses the [59-signal registry](review-proposals/pastor-contracts-v1/REGISTRY.md)
as a possible evidence supply. The registry remains intact as the contract for
current observations. Its blocked uses are safeguards, not a definition of what
PTE ultimately wants to know.

This exercise precedes the observed-profile consumer acceptance packet. It adds
no questions, runs no collection or evaluation, implements no projection or
clustering, and grants no production activation. The six existing proposals are
retained as the current-measurement slate; Brian's feedback supports that scope
in principle, without turning this design exercise into a new collection decision.

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

## Concrete missing-observation contracts to design next

The recommendation is to design reusable **evidence capabilities** that answer the
missing product questions, rather than adding one score for every desired noun.
These are design candidates, not implemented packs, model choices or approved
taxonomy changes. Existing collection questions stay frozen.

### G1 Bound propositions, adoption and qualifications — bounded capability proof

G1 goes first as a bounded proof of a reusable binding capability, not as the
start of exhaustive doctrinal extraction or a priority ranking above G2/G3. The
[prepared G1 contract and twenty authored cases](review-proposals/g1-binding-v1/REVIEW.md)
cover assurance and one synthetic city ramp proposition. They are contract examples,
not empirical evidence of model accuracy.

A sermon observation should identify a grounded claim span, voice, object/referent,
relation, polarity, conditions, stated qualification and explicit epistemic status.
A quote can be adopted, reported, rejected or unresolved; topic/function scores
cannot choose among these for a particular claim. Opposing propositions require
their own spans. Normalize only as far as the text supports; retain the source
wording and unknown fields. Code can validate bounds and retain candidates;
semantic claim binding needs its own versioned contract and review.

Prepare one small design exercise with two targeted downstream questions:
**assurance known/permanent/lost/retained under stated conditions**, and **a named
public object/proposition approved/opposed/prescribed**. These exercise theological
and public treatment distinctions without making a universal doctrine taxonomy.
This capability also supports C02/C04/C18/C20; it does not claim to solve all topics.

Prepared conceptual cases: “you may know acceptance now” without a permanence
claim; “can be lost if X” with a stated condition; approval of policy A plus
criticism of policy B; reporting a speaker's argument while rejecting it; an
explicitly unresolved alternative. Expected fields and non-characterizations
should be authored by PTE development before any model run. Projection must
retain qualified/mixed/date-specific claims rather than pick one overall stance.

### G2 Text/argument/application binding and development facets

The [G2 V1 contract](review-proposals/g2-g3-v1/G2_CONTRACT.md) now specifies
source nodes, semantic edges, performed operations and independent development
facets for C06/C10/C11/C13, with authored contrasts. These are observation designs,
not validated measures of depth or faithful interpretation.

Identify a grounded explanation episode and its subject/claim, biblical anchors
where present, stated reasons, explanatory steps, substantive distinctions,
engagement with alternatives, qualifications and worked implications. For an
application, identify the requested response, rationale, circumstances, obstacles
and concrete guidance. Count only demonstrable facets; episode length, vocabulary,
number of citations and presence of argument alone are insufficient.

A short passage can develop a precise distinction; a long passage can repeat a
bare assertion. One can be strong in explanation but weak in alternatives, and
another in concrete application without extensive doctrinal analysis. Preserve
that profile of facets. Require human assessment of the adequacy of an explanation;
facet presence is not a certification of soundness or depth in every subject.
This capability serves C06/C10/C11/C13 and supplies relational evidence for C14.
Reuse Scripture and grounded style evidence where compatible instead of rerunning
those collectors just to add links.

### G3 Observable pastoral address

The [G3 V1 contract](review-proposals/g2-g3-v1/G3_CONTRACT.md) now specifies
utterance–addressee–circumstance binding and adopted multi-act address patterns
for C12. It preserves qualifications and rejects inference of inner empathy or
actual listener effects. Authored contrasts are design expectations only.

Identify the listener circumstance addressed (for example grief, doubt or moral
failure), the pastor's address acts, the actual words supporting them, and relevant
qualifications. Distinguish acknowledgment/perspective-taking, reassurance,
challenge, warning, invitation and concrete care without declaring them a single
opposed kindness/harshness spectrum. More than one can occur in a passage.

A service appeal alone does not show acknowledgment of a sufferer's experience.
Acknowledging grief and giving a command to others are different observations.
Explicitly critical treatment may coexist with respectful recognition of a
person's difficulty. Claims must concern demonstrated address, not the pastor's
inner emotions, moral worth or listener experience. These authored contrasts
should define C12 before a new posture measurement is considered.

### G4 Articulated coherence and tension review

Reuse G1 propositions/conditions and G2 stated inferential links. Observe when a
speaker explicitly connects claims, qualifies their applicability, recognizes a
tension or offers reconciliation. Projection can then search for compatible and
apparently conflicting claims within matched subjects/scopes, preserving review
candidates and alternative explanations.

A saving-benefit → conduct claim and a conduct-as-condition claim are not necessarily
contradictory if they concern different benefits/conditions. Stable topic rates
say nothing about that distinction. Logical compatibility and sound inference need
bounded review; unresolved tension is not automatically incoherence, and no detected
conflict is not comprehensive coherence. No new global coherence Noul or pastor
quality Score is proposed.

## Recommended sequence and stopping conditions

1. **Retain the approved desired-profile direction.** Brian approved C01–C20 as
   the desired characteristic catalog and D01–D06 as downstream constructs, with
   their stated meanings and explicit unknowns. They are product requirements,
   not approved question packs or numeric features.
2. **Retain the approved bounded G1 design and explicit hold.** Assurance and one
   public-policy proposition remain its two subjects. Brian now directs no G1
   implementation or expansion yet; authored cases are not empirical proof.
3. **Retain the joint design decision and bounded G2 scope.**
   [G2/G3 contracts and the joint comparison](review-proposals/g2-g3-v1/REVIEW.md)
   are approved alongside G1. The [bounded G2 proposal](review-proposals/g2-feasibility-v1/REVIEW.md)
   now supplies a fixed packet, exact questions, controls, command and decision
   criteria. Brian executes provider/dataset validation; no broader work is activated.
   G2 serves developed treatment and G3 serves observable address. Designing them does not automatically
   authorize broader G1 extraction. G4 remains deferred and must reuse G1/G2
   claims and relations. Development prepares concrete bounded options; Brian
   chooses from reviewable proposals rather than designing experiments.
4. **Prepare projection rules for already suitable inputs** (attention, finite style,
   treatment, appeals, breadth and measured-pattern consistency) after their desired
   estimands are accepted. Treat coverage/validation gaps as such; do not create new
   semantics merely because current comparative use is gated.
5. **Then return to the provider-free consumer acceptance packet.** Its cases must
   exercise both the existing observations and missing desired fields. A sparse
   safe profile must visibly remain incomplete relative to the desired catalog.
   Only later prepare a separate bounded measurement validation and, ultimately,
   a concrete cost/scope/activation proposal for broader collection.

This changes the next step from implementing an observed-profile view to designing
what that view must eventually represent. The current registry remains the
measurement-side contract; this desired catalog is the product-side contract.
Their mapping, not either inventory alone, decides whether broader collection will
produce the pastor understanding PTE wants.

## Evidence basis and scope of review

This is a contract/inventory analysis, not an empirical accuracy or corpus-coverage
evaluation. Current support was checked against the [V1 registry](review-proposals/pastor-contracts-v1/registry-v1.json),
[canonical topic inventory](../src/pastor_transcript_extractor/sermon_topics.py),
[salvation definitions](../src/pastor_transcript_extractor/sermon_salvation_relationships.py),
[action/public/material definitions](../src/pastor_transcript_extractor/sermon_leaf_packs.py),
and [homiletic definitions](../src/pastor_transcript_extractor/sermon_semantic_dimensions.py).
Outside-registry Scripture and span evidence is documented in
[sermon analysis](SERMON_ANALYSIS.md#structural-scripture-profile-iteration-3) and
[semantic style analysis](SEMANTIC_STYLE_ANALYSIS.md#evidence-and-derivation-layers).
Their existence does not grant compatibility or readiness for the proposed new uses.


## Current evidence status and next architecture proposal — 2026-10-14

The desired C01–C20 and D01–D06 meanings and existing-registry gap matrix remain
intact. G2 and G3 have now passed **bounded construct feasibility**, with conservative
relation/binding recall limits. Neither makes the affected desired characteristics
fully measured in production. G2 does not validate every interpretive operation or
depth; G3 does not establish recurring posture, private empathy or listener benefit.
Automatic candidate discovery/recall and population opportunities remain untested.
G1 is approved as bounded design only, not provider/dataset feasibility; its
implementation/expansion hold persists. G4 remains deferred.

Close G2/G3 construct iteration. The [next architecture proposal](PASTOR_PROFILE_EVIDENCE_ARCHITECTURE.md)
returns to the product-first bridge: common provenance, distinct observations,
profile-field estimands/unknowns and coverage rules, then a provider-free consumer
acceptance packet. This is proposed design work, not activation of collection,
projection, comparison or quality scoring. The original recommended sequence above
is advanced by these bounded results; no further TypeSafe polishing is proposed.
