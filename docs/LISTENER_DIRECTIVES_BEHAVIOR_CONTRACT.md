# Listener directives: first development increment

Status: **Question-set readiness: PASS — ready for broader analysis**, accepted
by Brian on 2026-10-13 after V3. Validation is closed. Freeze the V3 questions,
router, target-only evidence boundary, and raw answers.
This pack asks what response the preacher requests from the listener. It does
not establish a saving relationship, theological position, actual response, or
pastor-level trait. Salvation V9 remains frozen.

## Proposed contract

`listener-directives-v3-help-people-in-need` contains nine independent Noul questions:
trust, repent, change behavior, spiritual practice, witness, serve, give,
participate, and civic action. The canonical definitions, inclusion/exclusion
boundaries, provider questions, and full question digest live in
[`sermon_leaf_packs.py`](../src/pastor_transcript_extractor/sermon_leaf_packs.py).
Several requests may occur together. Endorsed biblical instructions applied to
current listeners and inclusive “we should” language qualify. Narrative,
unendorsed quotation, rejected instructions, topical description, and prayer
addressed solely to God do not. Rhetorical form qualifies only when it actually
functions as an appeal. Adjacent context clarifies references; the target must
contain the request.

The approved (bounded-review scope) `listener-directive-route-eligible-v1-candidate` router includes
**every final projection-eligible block**, without a topic, keyword, or
application-probability filter. That is the coverage-first baseline for this
increment. It preserves current content-role, overlap, sparse-content, and
reviewed projection exclusions. The bounded run examines blocks outside the
salvation route, cue-rich blocks, blocks without cues, and additional coverage.
Cues select inspection cases; they neither label nor route production content.
This sample cannot establish corpus recall. Its policy version and selection
behavior remain unchanged after approval.

## Bounded inputs and decision

The defaults use cached broad-topic artifacts from reviewed sermons **1200,
590, and 4430**, with at most four unique eligible blocks per sermon. At most
two ineligible blocks per sermon appear as unevaluated controls. Twenty-four
[authored probes](../src/pastor_transcript_extractor/data/listener-directive-probes-v1.json)
provide explicit positive proposals for every leaf, independent overlaps,
narrative/quotation/rejection boundaries, applied commands, rhetorical appeals,
prayer-to-God exclusion, and context-only leakage. These are authored contract
examples, not labeled natural data or evidence of model accuracy.

The packet preserves exact target/context text, broad-source fingerprints,
source/database/WAL signatures, selected strata, independent raw probabilities,
resolved model IDs, and original request provenance. V1 evaluated 36 blocks
with nine questions each. V2 evaluated three revised questions per block.
V3 asks only serve: 36 new judgments on the same 36 blocks. With all refinement packs missing, the default six-block batching
requires at most seven initial requests before token-driven splitting or retries.
Cache hits reduce that count. No role, treatment, topic, or salvation questions
are requested. Read-only database access rejects changed inputs before publishing
a completed packet; successfully evaluated blocks remain cached for a retry.

Brian's [stage-gate decision](../evaluation/sermon-topics/listener-directive-stage-gate-v1.json)
accepts the router and directive evidence boundary, provisionally accepts trust,
repent, spiritual practice, witness, participate, and civic action, and requests
revision of change behavior, give, and serve. The original V1 review is retained
unchanged. Repent at .69 is an accepted near-cutoff observation, not grounds for
question or threshold tuning.

Brian's [V2 decision](../evaluation/sermon-topics/listener-directive-stage-gate-v2.json)
records the four overlap regressions as clean but withholds approval because
serve at 590:64 fell from .84 to .13. V1 and V2 reports remain unchanged.

V3 modifies only serve: an explicit appeal to help, meet needs, or beneficially
impact people in need qualifies, including material, social, or spiritual/gospel
need. A concrete care task such as meals or cleaning is not required. Merely
joining, donating, participating, praying, or witnessing remains insufficient;
service must be explicitly requested as help or impact on people in need.
The V2 change-behavior and give definitions, other six questions, shared evidence
boundary, router, probes, cohort, and provisional display cutoff are unchanged.

The V3 run recomputed serve on the same 36 cases and reused eight V2 answers.
All four original overlap regressions and all 24 authored overlap checks stayed
clean. Genuine service probes scored .98/.98/.94, and donation plus joining a
volunteer team remained .19 on serve.

Brian's [completion decision](../evaluation/sermon-topics/listener-directive-stage-gate-v3.json)
and [interpretation companion](../evaluation/sermon-topics/listener-directive-stage-gate-v3.md)
correct the expected actions at 590:64 to **participate, spiritual practice,
and witness**. The passage asks for gospel participation, witness, and prayer;
it does not clearly request care, meeting needs, or an act of help. Serve=.42
is reasonable secondary ambiguity, not a failure to be tuned away. The .70
review display cutoff remains unchanged and is not a collection threshold.
Repent=.69 also remains unchanged.

The acceptance companion recomputes the corrected diagnostic expectation from
saved V3 probabilities without calling a provider. Original V1/V2/V3 reports,
including their pending approval and serve-recovery fields, remain immutable
historical records; the separate decision records subsequent human acceptance.
Approval concerns measurement-question readiness, not universal pastor-level
sufficiency or automatic production collection. No more listener inference,
serve tuning, or cohort expansion is needed for this milestone.

## Cache contract

The registry extends the existing independent answer-pack cache and provider
adapter. Raw answer identity includes requested model, pack version, complete
question digest/questions, exact target and bounded context, context diagnostics,
and block provenance. It excludes batch membership, routing policy, review
labels, and display/collection thresholds. Changing a display policy reuses
answers; changing evidence or question semantics produces a miss. Malformed
answers are rejected and corrupt entries repaired. All-hit evaluation constructs
no SDK client and requires no credentials. The eight unchanged directives are reused from the fingerprinted V2 packet;
serve uses its own V3 refinement cache. The same generic composition method
checks per-leaf question equivalence, complete inventory, context, and model
before persisting the combined nine answers under the full V3 cache identity.
Later full-V3 requests can reuse that entry. Per-leaf source versions, digests,
and original request provenance preserve the V1/V2 lineage. Existing V1, V2,
and salvation cache identities remain unchanged. Review JSON and Markdown pairs are reused byte-for-byte or repaired
using the existing shared artifact writer.

## Completed validation and next handoff

The V3 completion decision was written provider-free. To reproduce or repair its
JSON/Markdown companion from the repository root:

```bash
.venv/bin/pte analysis listener-directives-review
```

The command now records accepted interpretation and does not construct a client
or reread classification data. The three raw review packets remain preserved.
The next question set is [public-life treatment](PUBLIC_LIFE_TREATMENT_BEHAVIOR_CONTRACT.md).
Its bounded run is the next handoff; do not rerun listener validation.
