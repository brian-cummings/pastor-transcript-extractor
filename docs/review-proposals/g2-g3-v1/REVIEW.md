# G1/G2/G3 joint design handoff

Status: **G1/G2/G3 designs approved; G2 and G3 bounded feasibility passed**.
G2 retains recall limitations; G3 retains conservative positive/context binding
limitations. Both construct iterations are closed. G1 remains design-only with
an explicit implementation/expansion hold; its authored cases are not empirical
validation. See the separate [G2 decision](../../../evaluation/g2-binding/feasibility-stage-gate-v2.md)
and [G3 decision](../../../evaluation/g3-address/feasibility-stage-gate-v2.md).
The [next architecture proposal](../../PASTOR_PROFILE_EVIDENCE_ARCHITECTURE.md)
recommends shared evidence/profile-field contracts and provider-free consumer
acceptance. Full collection, G4, projection/comparison and scoring remain held.
The original design tradeoffs below are retained as historical rationale.

Read [G2_CONTRACT.md](G2_CONTRACT.md) for C06/C10/C11/C13, [G3_CONTRACT.md](G3_CONTRACT.md)
for C12, and [CASES.md](CASES.md) for 28 authored contrasts. Full bound expectations
are in [cases-v1.json](cases-v1.json). These sit alongside the approved
[G1 representation](../g1-binding-v1/CONTRACT.md) and its 20 authored cases.

## What the designs contribute to the desired profile

| Capability | Product contribution | What it observes | What it does not establish |
| --- | --- | --- | --- |
| G1 | C03 assurance, bounded C08 policy positions, aspects of C20 qualification/uncertainty | Relation/object, voiced polarity, adoption, scope and conditions of exact source claims | Stable pastor beliefs, comprehensive doctrinal extraction, full candidate recall or coherence |
| G2 | C06 developed application, C10 text carrying teaching, C11 demonstrated operations, C13 development facets | Grounded episode nodes and semantic edges, actual operations, reason/response/guidance/obstacle and text/claim links | Correct interpretation, adequate reasoning, a global depth score, listener benefit or episode completeness without boundary review |
| G3 | C12 observable pastoral address | Adopted address act bound to a stated addressee/circumstance, with qualifications and multi-act patterns | Inner empathy, personal virtue, actual listener conditions/effects, or a kindness/harshness ranking |

G2 closes a different gap from G1: two pastors with similar propositions can develop
text, argument and application differently. G3 closes another: shared subjects and
actions do not establish how vulnerable people are addressed. These are complementary
product capabilities, not stages of an exhaustive doctrine pipeline.

## Prepared design decisions

Recommendation: adopt the following G2/G3 direction for design, without choosing an
implementation winner or granting a validation run:

1. Use common source-backed nodes, episode IDs, voice/adoption, context roles and
   unresolved states across all three; keep semantic meanings and use gates separate.
2. For G2, require evidence of each relation between the particular text, claim,
   reason or response. Keep proposed episode boundaries and performed versus
   self-described operations explicit. Retain independent development facets.
3. For G3, require an adopted address utterance and evidence binding it to the
   stated circumstance/addressee. Preserve multiple acts and qualifications;
   reports, prayers and historical address do not become present adopted address.
4. Preserve partial knowledge: a response can be concrete without a rationale,
   reasoning can be observable without a resolved Scripture anchor, and an
   adopted act can remain unbound to a circumstance. Abstain from only the stronger
   claim that needs missing information; do not manufacture its absence or opposite.
5. Keep judgment of depth, interpretive fidelity, adequate pastoral treatment and
   effect distinct from facet/act occurrence. Human review can use the structured
   evidence for candidate discovery; no hidden quality score is added.
6. Require independent-sermon coverage, matched opportunities, boundary review,
   missingness and uncertainty before profile tendencies/rates. No numeric threshold
   or universal sample size is approved. G4 must consume claims/relations, not
   infer coherence from a stable distribution or tone.

## Concrete joint comparison for the later implementation decision

| Candidate bounded implementation | Product benefit to test | Main design risk / validation burden | Reuse and independence |
| --- | --- | --- | --- |
| G1: assurance plus one city-ramp proposition | Can positions, voice/adoption and qualifications be bound without semantic leakage? | Claim candidates may omit/reframe propositions; polarity and adoption can invert meaning. Natural examples need coverage beyond authored vocabulary. | Common spans, voice and qualification records could support G2/G3. Successful G1 does not authorize expansion. |
| G2: one text-explanation contrast plus one developed-application contrast | Can the system distinguish similar subject/position presence from demonstrably different development? | Candidate episodes may be partial; proximity can become fake text/argument edges; facet counting can masquerade as depth. | Can start from local grounded statements and existing Scripture/style evidence without waiting for systematic G1 normalization. |
| G3: grief-address contrasts plus acknowledgment/challenge around moral failure | Can address acts be bound to circumstances without reading inner empathy or endorsing quoted advice? | Circumstance/addressee coverage, quoted speech, generic caring language and mixed address acts can distort pattern rates. | Can use its own utterance/circumstance nodes; share G2 response evidence and G1 adoption/qualification evidence where actually available. |

At the original joint design review, no harness or empirical measurement existed.
Subsequent bounded G2/G3 runs now supply the evidence above; no corpus cost/latency
or accuracy advantage is established for any option. G2 touches more desired characteristics; that is a product-benefit
consideration, not evidence that it will be easier or more accurate. G3 directly fills
the currently missing posture information. G1 offers bounded position/adoption tests.

**Joint review completed for design direction.** Brian selects the bounded G2
proposal first. This does not implement full G2 or activate validation on his behalf.
The candidate comparison above remains the recorded rationale and tradeoffs. Development must prepare the
candidate builder, fixed questions, controls, default inputs, exact bounded command
and proposed acceptance decision. Brian executes dataset validation; development
owns interpretation. The current choice is limited to preparing the small G2 harness/proposal; the
provider validation command has not been run.

## Authored contrast coverage

G2 has 14 examples: explained text versus adjacent reading; application with reason
versus concrete command alone; obstacle-sensitive guidance; answered alternative;
explicit distinction/qualification; vocabulary without development; context leakage;
rejected reported argument; truncated premise; method self-description; demonstrated
context reasoning with unresolved passage identity; own argument with worked implication.

G3 has 14: circumstance acknowledgment versus topic mention; possible perspective;
qualified reassurance; acknowledgment plus challenge; invitation plus offered care;
care self-description; rejected reported address; prayer; story address; context
resolution versus context-only act; unresolved circumstance/function; warning with challenge.

Authored cases exercise semantic boundaries and preserve exact source slices; they
are neither natural sermons nor model outputs. The local checker verifies grounding,
endpoint integrity and scope holds only. It cannot prove semantic accuracy, automatic
candidate recall, boundary quality, opportunity coverage or sufficient pastor evidence.

## Provider-free check

From the repository root:

```bash
.venv/bin/python docs/review-proposals/g2-g3-v1/build_cases.py --check
```

This checks 28 prepared cases, source/fingerprint consistency, relation/act endpoints,
target-grounded relation/act evidence, unassessed interpretation quality, absent inner-empathy
and listener-effect values, and the explicit holds on G1/G4/implementation priority.
No model, database or corpus is accessed. This is an artifact check, not a validation run.

G1, G2 and G3 now have comparable contract/specification artifacts. Their existence
removes the earlier design-order obstacle; it does **not** override Brian's explicit
hold on G1 implementation/expansion, grant new question semantics or authorize broad
collection. G4 and the consumer acceptance packet remain deferred.

The authored G2/G3 case artifact retains its original design-stage hold/priority
metadata as historical context; the current authorization is recorded above and
in the feasibility handoff. It does not authorize G1/G3/G4 implementation.


## Current architectural decision proposal — 2026-10-14

G2/G3 evidence supports proceeding to the evidence-to-profile bridge, without
claiming all desired C06/C10/C11/C12/C13 characteristics are measured in production.
Preserve G3 circumstance relevance separately from human-recipient circumstance
binding; current-listener adoption remains a composition with independent framing.
No further construct-tuning calls are proposed. Candidate discovery/recall,
calibration, denominators and request economics are later validation tasks.
The next concrete design artifact is [the evidence architecture proposal](../../PASTOR_PROFILE_EVIDENCE_ARCHITECTURE.md);
consumer implementation, G1 and collection still need separate decisions.
