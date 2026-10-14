# Public-life treatment: first development increment

Status: **Treatment-question readiness: PASS**, accepted by Brian after V2.
Treatment validation is closed. The .55 router is rejected for coverage;
eligibility-only routing is implemented as a proposal pending routing review.
Listener directives and salvation measurements are frozen.

The downstream question is: **How does the preacher treat public affairs in this
block?** The pack has eight independent Noul questions: descriptive, illustrative,
theological, moral, critical, supportive, prescriptive, and advocative. Canonical
meaning and exclusions live in
[the shared pack registry](../src/pastor_transcript_extractor/sermon_leaf_packs.py).
This is a proposed measurement contract, not an approved taxonomy.

Description reports public events or processes. Illustration uses public life
to explain another point. Theological and moral framing require explicit
relationships or judgments. Critical/supportive treatment requires the preacher's
own evaluation, including adopted positions; reported criticism or praise does
not establish endorsement. Policy prescription is distinct from mobilizing
listeners to take civic action. Several functions may coexist, and different
public objects may receive different evaluations in the same block. Raw results
do not identify a pastor's party, political ideology, or stance across sermons.

Only target text establishes treatment. Adjacent sentences clarify references
but cannot independently supply it. Private morality, a merely quoted party
claim, passing civic vocabulary, and neighboring religious language are boundary
controls. A narrated event may be descriptive or illustrative without endorsement.

The candidate router requires current final content projection eligibility plus
cached `society_public_life` Supporting-or-above probability mass of at least .55.
This uses the Score distribution rather than confidence. The .55 route is pending
review; it is not inherited approval from the salvation router. The review samples
up to four unique eligible blocks from each of videos 1200, 590, and 4430: strong
public-topic signal, near the route boundary, below-route shadow, and absent-topic
control. Unavailable strata are reported rather than silently filled. Shadow and
absent blocks are evaluated only as bounded routing diagnostics. Ineligible
content remains visible but is not sent to the provider.

[Eighteen authored probes](../src/pastor_transcript_extractor/data/public-life-treatment-probes-v1.json)
prepare positives for every leaf, independent overlaps, reported and rejected
positions, private-conduct negatives, history without endorsement, and context
leakage. Authored expectations are concrete proposals for review, not gold truth
or evidence of corpus accuracy. Natural cases require interpretation after the
run; Brian does not select cases or author annotations.

At most 30 blocks produce 240 judgments. The eight new questions use the existing
independent per-block cache, provider adapter, six-block batching with token-driven
splitting, payload validation, and shared JSON/Markdown writer. Existing role,
treatment, topic, listener, and salvation questions are not requested. Pack/version,
complete question digest, exact target/context, model, and provenance determine
cache identity; routing, review display policy, and batch membership do not.
Repeated unchanged runs reuse raw answers without creating an SDK client on hits.
Source/database/WAL signatures reject changing inputs before report publication.

The .70 display cutoff is provisional and is not a collection threshold. Propose
acceptance only after examining preacher attribution, overlaps, natural treatment
positives, and below-route cases for routing misses. This first boundary test does
not establish corpus recall or pastor-level sample sufficiency. Ordinary
reclassification does not activate this pack.

## Completed question validation and routing handoff

The [V2 completion decision](../evaluation/sermon-topics/public-life-treatment-stage-gate-v2.json)
freezes the eight questions at digest
`81bb09e1b660cbd3aa4838b1c528a16ea20bbd66806bca7526856de81d39f079`,
bound to saved V2 review fingerprint
`8930a9ad6776bf3267a6593776cd5e1028ce74895211eca871433c666f092048`.
No treatment V3, threshold change, or additional treatment inference is required.
Historical raw V1/V2 reports remain unchanged.

The [routing comparison](../evaluation/sermon-topics/public-life-routing-comparison-v2.md)
evaluates eligibility-only routing against the .55 gate using saved V2 answers.
The deliberately stratified ten natural cases give 4 old-routed versus 10
eligibility-routed blocks. Both explicitly reviewed misses (4430:34 and 1200:26)
are recovered. All saved ineligible-content controls remain excluded. Three
eligible absent-topic controls have no displayed treatment; including such
negative blocks is part of the coverage/workload tradeoff. The additional
590:60 displayed theological signal needs interpretation and is not promoted to
a third reviewed ground-truth miss.

Recommend **eligibility-only routing** before broader collection. Public-topic
support can prioritize or stratify review but must not decide whether a valid
sermon block receives these questions. The coverage candidate is
`public-life-route-eligible-v2-candidate`; it requires strict current final
projection eligibility, not public-topic support, a keyword, or a listener
advocacy signal. Questions, .70 display policy, and cache identities are unchanged.
Current eligibility must be reassessed during actual collection. Broader collection
remains inactive pending review of this concrete routing proposal.

The comparison made zero provider calls and did not read classification files or
the database. It is not a corpus recall or cost estimate. The historical
`eligible_block_count` source field actually counted candidate-routed blocks;
its correction now reports total eligible and candidate-routed counts separately
in future preparation. Archived artifacts are preserved and cannot supply an
eligibility-only corpus workload estimate.

To reproduce or repair the two provider-free report pairs:

```bash
.venv/bin/pte analysis public-life-treatment-review
.venv/bin/pte analysis public-life-routing-review
```

These commands consume saved evidence only and reuse exact output pairs. Review
the routing proposal rather than rerunning treatment validation. No larger cohort
or broad backfill is started by either command.

## V1 interpretation and minimal V2 refinement

The [provider-free assessment](../evaluation/sermon-topics/public-life-v1-semantic-assessment-v1.md)
weighs the supplied advice against the plan. Preserve independently evidenced
perspectives; do not force a single label or invent block-wide exclusion between
support and criticism of different objects. This pack does not identify the
object/proposition to which a stance applies, so topic/treatment co-occurrence
cannot alone answer which specific policy or actor a pastor endorses.

Revise only **descriptive** (reporting another actor's remarks remains factual
information without endorsement) and **prescriptive** (require a separately stated
public ought-claim, specified rule, change, or outcome; include public institutions
and a church in its public role). Criticism, moral judgment, and listener advocacy
alone do not establish institutional prescription. Explicit repeal remains a
public policy outcome that may coexist with advocacy.

Keep the other six questions unchanged. Add moral to authored expectations 14
and 16 because the normative rejection carries independent moral evaluation.
Do not revise questions to force .69 above the unchanged .70 display cutoff.
This tests semantic separation rather than exact match against incomplete labels.

The saved V1 fingerprint is
`4134e90dd540f5f8bb0d263091ee44605b1dee37944633c472dc1ef15d714b77`.
V2 reruns only two questions on the exact 28 source cases (56 new judgments),
reuses six baseline answers, and persists a provenance-rich composed eight-leaf
V2 cache entry using the same shared composition method as listener refinements.
The source texts, cohort, probes, other questions, and cutoff remain unchanged.
The report compares the six focused authored cases and all below-route natural
cases with their raw probabilities. Brian runs the same command above; Codex
interprets the resulting V2 packet before recommending question readiness.

Do not approve the .55 router unchanged for broader treatment coverage. V1
1200:26 and 4430:34 establish meaningful treatment below it. The router remains
unchanged for the fixed-case rerun; an eligibility-only broader routing policy is
a concrete proposal to consider separately, not an activated change or a claim
of corpus recall. No larger cohort, pastor-level study, collection-threshold
calibration, or new listener/salvation inference is part of this increment.
