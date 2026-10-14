# Bounded G1 design handoff

The desired catalog C01–C20 and landscape constructs D01–D06 are approved as design
direction. Brian now approves this bounded G1 design direction and explicitly
holds implementation and expansion. The [G2/G3 joint design handoff](../g2-g3-v1/REVIEW.md)
now precedes any choice of implementation/validation priority.

Read [CONTRACT.md](CONTRACT.md) for the binding representation and collection/projection
boundary, and [CASES.md](CASES.md) for the twenty prepared contrasts. Every case has
source-grounded expected records in [cases-v1.json](cases-v1.json).

## Approved bounded design direction

The approved direction adopts the G1 proof vocabulary and bound-record structure for these two questions only:
assurance knowability/loss/retention, and the city ramp requirement. In particular:

- Keep relation, voiced polarity, expression, speaker/adoption, object and qualifications
  separate; no block-wide stance label.
- Allow context to resolve an object while requiring the assertion in the target.
- Preserve explicit uncertainty and unanswered questions without converting them to
  denial or assuming both mean the same thing.
- Preserve reported/rejected claims without manufacturing the preacher's adopted opposite.
- Retain independently supported claims and scope diagnostics; keep different objects distinct.
- Treat grounded candidate coverage and semantic binding as additional prerequisites;
  source-offset validity alone cannot establish either.

The proposed implementation shape uses code-owned source candidates and narrow typed
judgments; this packet implements only authored case preparation and structural checks.
No provider answers are present. A fixed finite vocabulary is appropriate for the proof;
it is not approval of a theological taxonomy or evidence that all sermon claims are covered.

## Structural check already available

From the repository root:

```bash
.venv/bin/python docs/review-proposals/g1-binding-v1/build_cases.py --check
```

This is a local artifact check, not model or dataset validation. It verifies the 20
case IDs, literal source slices and fingerprints, relation/object vocabulary, evidence
for stated scope/uncertainty, target-only assertions, and the G2/G3 expansion guardrail.
The checker deliberately does not decide whether a source phrase semantically supports
the expected interpretation; those expectations are authored proposals for review.

## Empirical proof is a later, separately prepared milestone

Brian directs no more G1 work at this stage. This future milestone is conditional
on the joint G1/G2/G3 implementation decision; it is not the next authorized task.

A reusable binding capability is not empirically demonstrated by this packet.
Before a bounded model validation, development must supply a working candidate builder,
versioned narrow questions, a bounded harness, fixed natural controls and exact default
command. Brian runs that command; development interprets each failure mode and recommends
acceptance or narrow revision. No open-ended annotation or case selection is assigned.
There is no provider/dataset command to run now, and no broad collection is authorized.

Require demonstrated distinctions for current knowability versus permanent security,
affirmation versus denial versus open issue, own/adopted versus reported/rejected voice,
claim-specific qualifications, context-only leakage, referent failure, and different-object
contamination. Explicitly review candidate omissions and semantic binding beyond coordinate
validity. Authored successes alone cannot establish natural-sermon recall.

## Sequence guardrail

G1 is first to test a reusable evidence structure across two subjects. It is not ranked
above the pastoral and developed-teaching requirements of G2/G3. **Design G2 and G3 before
any additional theological topics are added to G1**, even if a future bounded validation
passes. Reuse a successful evidence structure where useful; do not grow a doctrine catalog
while deferring Scriptural/argument/application development and observable pastoral address.
G4 coherence should reuse claim and relation evidence. Consumer acceptance and broader
collection remain deferred by the product-first plan.

The G2/G3 contract designs are now prepared for joint review. Their existence does
not release the explicit hold on G1 implementation/expansion or activate validation.
