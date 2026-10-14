# PastorProfile evidence architecture: next-step proposal

Status: **design proposal, not implementation or collection authorization**. C01–C20 and D01–D06 remain the product requirements. G2 bounded feasibility is PASS with known recall limitations; G3 bounded feasibility is PASS with conservative positive/context binding limitations. G1 has an approved bounded design and authored structural cases, **not a provider/dataset feasibility PASS**; implementation and expansion remain held. G4 is deferred.

The next architectural step is to specify how compatible observations become explainable profile fields while retaining their scope and unknowns. Follow that with a provider-free consumer acceptance packet. Further G2/G3 prompt tuning is closed. No new TypeSafe calls are needed for this design step.

## Shared evidence, distinct meanings

Use a common provenance envelope around capability-specific records. Shared source wording can support different observations without being counted as independent evidence multiple times. Reuse compatible Scripture/style anchors and existing collected leaves; an incompatibility is explicit rather than repaired by recollecting equivalent evidence.

| Common envelope | Required meaning |
| --- | --- |
| Source locator | Recording/source identity, transcript version/hash, exact target spans, segment/time locators, leading/trailing context with separate roles. Context never becomes target evidence silently. |
| Unit and boundary | Candidate/utterance/node/episode identifiers; proposed versus reviewed boundaries; local sufficiency distinct from complete episode or sermon coverage. Stable IDs must account for source version and span identity. |
| Ownership and eligibility | Effective reviewed speaker membership and recording/content eligibility, with policy version. A pilot's video locator alone does not certify eligible pastor evidence. |
| Measurement provenance | Capability/question semantics and version, candidate-builder identity, resolved model, raw distributions, decision policy, reuse origin and semantic-review status. A reused answer remains attributable to its original question/run. |
| Independence | Underlying utterance/episode, sermon and series/period groupings. Overlapping candidates, duplicated uploads, repeated illustrations and correlated series are not independent occurrences. |
| Availability | Not collected; incompatible; candidate coverage unknown; boundary incomplete; judgment withheld; reviewed positive; reviewed negative in a specified unit. These are distinct states, never one zero. |

Shared voice/adoption infrastructure is desirable, but identical labels do not guarantee identical question meanings. G1's claim adoption, G2's reasoning/response adoption and G3's address adoption retain their own referent and provenance. Do not merge or reuse judgments without exact state and semantic compatibility. Reported material remains searchable evidence; attribution to a pastor requires separate gates.

| Capability-specific evidence | Preserve independently |
| --- | --- |
| Existing registry leaves | Measured subject/treatment/action/style occurrence and original allowed-use contract. Nearby leaves do not stand in for richer observations. The three unavailable salvation leaves stay unavailable. |
| G1 proposed claims | Object, relation, voiced polarity/expression, scope/conditions, voice/adoption. Absence of an answer is not uncertainty or denial; rejection does not invent an opposite claim. Missing collection remains visible. |
| G2 demonstrated relations | Directed text/explanation, reason/claim, grounding/response, qualification, step and obstacle edges; independent facets and partial endpoints. Relation occurrence is not reasoning adequacy, depth, fidelity or complete interpretive method. |
| G3 observable address | Independent acts; circumstance relevance; human-recipient circumstance binding; addressee; voice/adoption; local boundaries. Relevance to grief can coexist with prayer to God or reported address. Neither establishes current-listener posture. |

For G3, current-listener address is a composition of the independent observations; it is not a replacement for them. Positive relevance with withheld recipient binding retains the known act/relevance and withholds the stronger claim. A negative binding does not erase a real invitation to another group.

## From observations to a desired field

A proposed `ProfileFieldEvidence` contract should contain:

- Characteristic ID (C01–C20), exact estimand and allowable wording; the product question is defined before selecting signals.
- Compatible source observations and required gates. List absent required observations explicitly, including unavailable G1 positions.
- Supporting examples, counterexamples and unresolved examples with original evidence links and source/review scope.
- Coverage/opportunity description, independent-sermon and series/period counts, boundary and candidate-discovery status, and relevant uncertainty.
- Claim level: local example, reviewed-sample pattern, recurring pastor characterization or comparative construct. Stronger levels require additional declared gates.
- Suppression/withholding reasons, interpretation version and input provenance. Do not infer a universal pastor trait from an isolated sample.

Start with the strongest statement the actual inputs support, not the strongest desired product statement. A validated question meaning and a bounded feasibility result are prerequisites for some uses; neither is a complete profile validation.

| Desired field | Available next architectural treatment |
| --- | --- |
| Topic attention/basic style/treatment/appeals/breadth | Define estimands using the existing registry and compatible structural evidence, retaining existing sampling and use gates. No new semantics or collection follows automatically. |
| C03/C08 position, C20 expressed uncertainty | Represent required G1 observations and current missingness. Approved design is not observed data. No theological position is inferred from attention/treatment labels. |
| C06/C10 application and text development | Evidence-linked local G2 examples are representable. Recurrence, opportunity coverage and collection reliability still require validation. |
| C11 interpretive tendencies, C13 depth of treatment | The bounded G2 experiment validates certain relations, not the full operations inventory or depth. Display specific demonstrated facets and missing operations; no global depth score. |
| C12 observable pastoral address | Represent separate acts and relationships. Positive bindings withheld by G3 remain unresolved. Inner empathy, benefit and overall posture remain unestablished. |
| C14 coherence | Explicitly unavailable pending separately approved G4 design/validation reusing G1/G2. No coherence claim from stable distributions. |
| D01–D06 landscape/discovery | Keep as downstream constructs. No clusters, ranking, exemplarity or quality label from sparse/incompatible inputs. Evidence-backed discovery examples require their own scope and review rules. |

## Projection and denominator rules to settle next

Write proposed estimands before choosing thresholds. An example count, whole-measured-sermon occurrence and circumstance-opportunity-conditional rate answer different questions. A retrieved candidate catalog provides none of those population denominators by itself.

For each field, specify the eligible measured population, actual detection/assessment coverage, episode-to-sermon deduplication, conditional opportunity definition, series/period handling and negative-observation requirements. “Not detected in selected candidates” is not “absent from the sermon.” Unknown opportunities or candidate recall preclude an apparently precise rate. No universal sermon-count threshold or numerical recurrence cutoff is approved.

Recurrence must refer to independent eligible sermons, with stated time/series coverage and counterevidence. Missing measurements do not make a pastor less distinctive or less caring. Comparisons require compatible definitions, coverage/opportunities and uncertainty; profile missingness must not become a distance or cluster feature accidentally.

These are proposed contracts to develop, not operational estimators. Broader collection and projection activation require separate concrete implementation/validation and cost proposals.

## Provider-free consumer acceptance packet: concrete next deliverable

Prepare fixed synthetic examples plus source-linked frozen observations, with an explicit distinction between design fixtures and real measured evidence. Include the following expectations before any consumer implementation:

| Case | Required consumer behavior |
| --- | --- |
| Rich topic/style leaves without G1/G2/G3 | Useful measured fields plus visible missing positions/development/address; no completed-profile claim. |
| G2 text explanation versus adjacent unrelated assertion | Link only the supported text/explanation; no depth or interpretation-quality credit. |
| G3 prayer relevant to grief | Retain relevance, God addressee and negative human-recipient binding; no grief-listener posture credit. |
| Reported/rejected act or claim | Show the reported evidence with stance; no adopted opposite or current-listener attribution. |
| Known act/relevance, withheld positive binding | Retain partial observation and suppression reason; neither zero occurrence nor confirmed posture. |
| Context-resolved reference versus context-only act | Permit referent resolution; prohibit importing missing target treatment. |
| Duplicate/overlapping passages and series repetition | Preserve source references without inflating independent evidence. |
| Version/eligibility/ownership conflict | Mark incompatible or excluded evidence explicitly; no silent pooling. |
| Unknown candidate recall/opportunity coverage | Show examples, withhold population rate and recurring/comparative claim. |
| Contrary adopted claims with different objects/scopes | Retain differences and unresolved review need; no automatic incoherence. |
| Two similarly themed pastors with different supported examples | Explain the observed differences and evidence limits; no ranking or cluster assignment. |

The packet should define exact input schemas, expected visible wording/unknown states and provider-free checks. Brian reviews a prepared result, not designs annotations or JSON. Passing it would establish consumer behavior on supplied evidence, not automatic discovery or population inference.

## Recommendation and holds

Proceed next with the shared evidence/field contract and provider-free consumer acceptance packet, including proposed projection estimands. This advances the desired PastorProfile architecture without another measurement-tuning cycle or premature collection. It also exposes whether the evidence can support useful partial profiles before paying to collect it broadly.

G1 remains held pending a separate explicit implementation decision. Candidate-discovery recall, production calibration, opportunity denominators and request economics are named later validation/implementation tasks. G2/G3 construct feasibility is closed; full capability collection, G4, pastor projection/comparison and quality scores are not authorized here.

## Prepared shared contract and consumer packet — 2026-10-14

The [V1 review packet](review-proposals/profile-evidence-v1/REVIEW.md) now supplies
the shared evidence/field contract, complete C01–C20 field mapping, seven proposed
estimands and 17 provider-free acceptance cases. Exact schemas, pinned original
source/result references, visible wording, missingness and suppression reasons are
prepared. Frozen G2/G3 decisions retain their actual withholdings alongside clearly
marked synthetic designs. Integrity checks are separate from a future consumer
acceptance run; no production consumer or projection is implemented. All holds
above remain in effect. The packet proposes useful passage-level partial views
before any broader collection decision.

## Bounded observed consumer — 2026-10-14

Following Brian's explicit authorization, `pte analysis observed-profile-review`
now renders the supplied-passage view and runs all 17 consumer cases. The
[acceptance report](../evaluation/observed-profile-consumer-v1/REVIEW.md) records
17 invariant passes and 15 exact frozen state/link matches, with two conservative
differences reviewed and accepted by Brian. This bounded step is **accepted and closed**. The view is useful for evidence inspection while
preserving all 20 field questions, missing inputs and suppression reasons. It is
not the final PastorProfile projection layer. G1, broader collection, pastor
projection/comparison, clustering, G4, recurrence/rate estimation and scoring remain held. No next validation or implementation step is authorized by this acceptance.


## Separately authorized bounded G1 pilot — 2026-10-14

After closing the accepted consumer step, Brian explicitly authorized bounded G1
implementation and measurement feasibility. The [fixed pilot](review-proposals/g1-feasibility-v1/REVIEW.md)
is prepared behind `pte analysis g1-feasibility-review`: 28 cases, 37 source
candidates, 486 independent questions, 37 cumulative attempted requests, zero
SDK retries. No provider run or semantic feasibility verdict exists yet. Brian
runs the command; Codex then interprets the local records and recommends a bounded
feasibility decision before stopping. G1 full collection/expansion and all broader
collection, coverage/calibration/denominator/economics, projection/comparison,
clustering, G4, recurrence/rate and quality-score work remain held. This does not
reopen the accepted observed consumer or G2/G3 construct tuning.


## One G1 V2 local-observation refinement — 2026-10-14

Brian's G1 V1 result supports continuing bounded feasibility, not acceptance.
The [V2 handoff](review-proposals/g1-feasibility-v2/REVIEW.md) prepares only negation,
proposition voice/adoption and public attitude-versus-prescription question
clarifications on the same 28 cases/37 candidates. 338 answers are reused unchanged;
148 judgments are recomputed under a 37-attempt ceiling. V1 expectations and source
windows remain frozen. Brian runs `pte analysis g1-feasibility-review --revision v2`;
Codex then interprets corrections, legitimate withholding, remaining failures and
any disputed expectation before recommending whether to close bounded G1 feasibility.
No V2 result or acceptance exists yet. No further iteration, collection, pastor
projection/comparison, recall/calibration/denominator/economics work, recurrence/rates,
G4, contradiction/coherence or quality scoring is authorized.
