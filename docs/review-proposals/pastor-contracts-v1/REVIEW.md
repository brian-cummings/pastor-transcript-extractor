# Pastor contracts V1: prepared decisions and next handoff

Status: **current-measurement contract proposal; no production effect**. Brian supports
the six proposals in principle as safeguards around current measurements. The
[desired-profile gap analysis](../../PASTOR_PROFILE_GAP_ANALYSIS.md) now precedes
consumer acceptance work and defines the product requirements beyond this registry.
This iteration instantiates
all 59 signals from the downstream design in a versioned registry. It starts no
collection, classification, projection engine, or clustering work.

Read the [59-record summary](REGISTRY.md), or inspect [complete records](registry-v1.json).
The [design document](../../TYPESAFE_TOPIC_ANALYSIS_PLAN.md#downstream-pastor-understanding-contract--2026-10-13)
remains the downstream architecture authority. The [builder/checker](build_registry.py)
imports only local canonical question definitions, never provider clients or a database.

## What is concrete now

Every record contains the downstream statement, signal kind, inadequate-evidence
wording, forbidden claims, canonical question and digest, observation threshold
where one is already approved, route and limitations, evidence granularity,
exclusivity rule, projection estimand and denominators, conflict/temporal/missingness
rules, diagnostic flags, and use gates. Shared policies are normative and referenced
by each record. Family defaults are materialized in each projection record so that
exceptions are inspectable without reconstructing a taxonomy.

IDs are namespaced (`S:faith_as_receiving_response`, `L:trust`, etc.). A semantic
characteristic is distinct from its collection leaf. The proposed shared-characteristic
links identify overlap to investigate; they do not automatically merge independently
measured signals. Topic assignments are catalog navigation, not observed attachment
of an action or treatment to a topic.

Canonical cache digests and position-zero question digests are separately labeled:
topic/salvation pack digest functions hash inventories, while the Noul registry hashes
complete questions. Homiletic questions lack a canonical pack-digest function;
the registry records that fact and supplies its own complete-questions digest.
No question, threshold, cache identity, routing implementation, or readiness artifact
has changed. The JSON fingerprint covers both authored policy and copied semantics.

## Prepared decision slate

Brian can approve the slate or identify a numbered proposal to reject. Acceptance
records design intent and routing preference; broader collection still requires a
separate prepared activation proposal. No experimental selection, JSON authoring,
or annotation is requested.

| # | Concrete proposed decision | Evidence / consequence |
| --- | --- | --- |
| 1 | Adopt `pastor-leaf-contracts-v1` for scoped observed-corpus descriptions and grounded passage candidates. | Each leaf has a permissible statement; all stable traits, pastor comparison and clustering remain blocked until their explicit prerequisites are met. |
| 2 | Accept `public-life-route-eligible-v2-candidate` as the intended future collection route. Keep topic support for sampling/prioritization only. | [Ten saved cases](../../../evaluation/sermon-topics/public-life-routing-comparison-v2.md): .55 routes 4, eligibility-only routes 10, recovering both explicitly reviewed misses at 4430:34 and 1200:26. This does not estimate corpus recall or workload. |
| 3 | Keep salvation's frozen .55 route and nine frozen observation thresholds for the initial **policy-relative observed** use; do not claim exhaustive absence or unbiased prevalence outside that route. | [Existing uncertainty packet](../../../evaluation/sermon-topics/salvation-pastor-uncertainty-v1.md) preserves all-sermon versus routed-only denominators. Known below-route miss 590:26 remains a limitation. Absence-sensitive/comparative use would need a separately prepared coverage design. |
| 4 | Keep the three unresolved salvation leaves raw-only and excluded from projected values. | Neither more sermons nor a threshold supplies the missing semantic discrimination. The registry outputs unavailable, never zero or a contrary belief. |
| 5 | Require a separate grounded-evidence/observation decision policy for listener, public-life, material and homiletic occurrence rates. Use raw probabilities as diagnostics until it exists. | .70 review-display cutoffs are not collection thresholds; source/material's accepted .63 historical boundary and film/story ambiguity show why display alone cannot certify a claim. Frozen validated questions stay closed. |
| 6 | Keep assurance permanence/loss, named public policy positions, interpretive method, empathy, depth and coherence explicitly unavailable in the initial profile. | The current presence/function leaves cannot support these distinctions. Passage candidates can still surface for human reading; no substitute quality metric or new question pack is created. |

Default recommendation: **accept all six proposals as design direction**. Public-life
routing is the only new route acceptance decision in this slate. Listener/source
eligibility-only routes remain accepted; no approval is requested again for them.

## Evidence and denominator defaults

- An occurrence statement requires grounded target evidence, accepted sermon boundaries,
  effective reviewed identity, compatible canonical semantics and a stated corpus scope.
  One passage supports “observed in this sermon,” not a stable trait.
- An existing frozen salvation threshold selects policy observations, not automatically
  reviewed truth. Keep threshold selection, source evidence, and claim review distinct.
- Summarize independent sermons; duplicate uploads/extracts never increase recurrence.
  Unknown independence prevents a recurrence claim. Episode counts remain unavailable
  until a grounded episode/merge policy is prepared.
- Topic attention uses time-weighted normalized Score inside each measured eligible sermon,
  then equal-sermon aggregation. Report eligible versus measured time separately.
- Salvation primary observed-sermon fractions include fully route-measured zero-route
  sermons with the explicit policy-relative qualifier. The secondary routed-only fraction
  excludes only zero-route sermons. Incompletely route-measured sermons are missing.
- Other occurrence fractions require all eligible blocks measured for the primary selected
  sermon denominator and an approved evidence/decision policy. Preserve incomplete-sermon
  counts. Action/material/homiletic conditional denominators refer to their finite measured
  inventories, not every possible action/source/function.
- Recurrence, stable positions and quantitative feature use have no approved sufficiency
  rules yet. `minimum_sermon_count: null` is deliberate. Counts, series/period coverage and
  sensitivity must be shown rather than converted to an invented universal threshold.
- Conflicting positions require the same object, proposition, conditions and scope. Silence
  and low yes-probabilities are not opposing propositions. Unknown dates block temporal
  change claims; upload dates do not repair missing sermon dates.

## Prepared acceptance cases

These cases are retained for a later consumer implementation, after the
desired-profile and missing-observation contracts are settled. They
are contract examples, not new pastor judgments, synthetic model results, or a
completed projection test. The existing references provide evidence where noted;
future implementation must resolve source spans and review identities before rendering
actual profile claims.

| Case | Prepared input / reference | Required result | Forbidden result |
| --- | --- | --- | --- |
| Sparse observed relationship | Clouzet's faith-as-reception has one positive sermon in the [12-sermon packet](../../../evaluation/sermon-topics/salvation-pastor-uncertainty-v1.md). | Show isolated observed support and sample/series limits; recurring/stable status remains unavailable. | “Faith reception is his established characteristic” based on one sermon. |
| Multiple independent observations | Ryder's divine initiative has eight positive sermons in the 11-sermon packet. | Show policy-observed sermon count and separately the historical primary mean (.317), which is an equal-sermon average of within-sermon collected-block fractions. Do not relabel that mean as the new sermon-with-evidence fraction (8/11). Recurrence still requires a claim-specific sufficiency rule. | Eight minutes or duplicate uploads counted as eight independent sermons; treating .317 as belief strength. |
| Zero positive evidence | Clouzet's justification has zero positive sermons in the packet. | “Insufficient positive evidence under this route and detector.” | Rejects justification, or a zero theological position. |
| Unknown time/series | Ryder has five unknown-period and seven unknown-series sermons in the packet. | Preserve unknown counts and restrict temporal/cross-series claims. | Fill sermon dates from uploads or infer a change in theology. |
| Route omission | Public 4430:34 and 1200:26 are below the .55 gate but have reviewed treatment. | Historical unrouted means unknown; proposed eligibility route includes them after current eligibility is reassessed. | Unrouted equals negative public treatment. |
| Overlapping source/form | [4430:57](../../../evaluation/sermon-topics/source-material-stage-gate-v1.md) has personal testimony .70, reported testimony .88 and quotation .88. | Preserve all three independently meaningful observations and shared evidence; no automatic triple weighting in comparison. | One dominant source label or three independent sermons. |
| Different objects versus contradiction | Authored scenario: one sermon approves public object A and criticizes object B. | Keep both treatments; unavailable object binding prevents a specific-position conflict claim. | Mixed belief about A inferred from marginal support/criticism. |
| Duplicates and unavailable comparison | Authored scenario: two uploads of the same teaching occasion, plus two profiles with no adequately shared approved dimensions. | Count one independent sermon; comparison returns not-comparable with missing-dimension reasons. | Artificial recurrence, missing dimensions filled with zero, or an opaque similarity result. |

A further projection implementation must keep the historical salvation packet's
collected-block-fraction means separate from this registry's proposed sermon-with-evidence
fractions. Both can be diagnostic with named denominators; they are different estimands.
The registry does not reinterpret historical numbers or implement either calculation.

## What remains before broader collection

The contracts are complete as the current-measurement inventory, not the desired
PastorProfile. The [desired-profile gap analysis](../../PASTOR_PROFILE_GAP_ANALYSIS.md)
defines C01–C20 product characteristics independently of these leaves and maps their
information requirements to current evidence. It separately defines D01–D06 landscape
constructs. Do not proceed to the observed-profile consumer acceptance packet yet.

The [bounded G1 proof specification](../g1-binding-v1/REVIEW.md) is approved as
an evidence-structure design, with implementation and expansion explicitly on hold.
The [G2/G3 contracts and joint comparison](../g2-g3-v1/REVIEW.md) are now prepared.
Review all three before choosing what deserves a bounded implementation/validation
first. G2 addresses C06/C10/C11/C13, G3 addresses C12, and G4 remains deferred to
reuse G1/G2 claims and relations. All cases and proposals are prepared by development.
The eventual consumer packet must show missing desired characteristics, not redefine
the product as only what this registry can safely report today.

Before any paid broader run, separately prepare the collection scope/cost defaults,
evidence granularity and decision-policy requirements, current eligibility/identity
handling, failure/missingness accounting and activation proposal. Accepting a routing
policy or this registry does not activate that run. No taxonomy redesign, frozen-question
recalibration or broad evaluation is required for the present design review.

## Exact provider-free check

From the repository root:

```bash
.venv/bin/python docs/review-proposals/pastor-contracts-v1/build_registry.py --check
```

This checks all 59 canonical leaf IDs, question/digest alignment, frozen salvation
thresholds, unresolved-leaf exclusions, shared-policy references, inactive use gates,
fingerprint and JSON/Markdown reproducibility. It reads local definitions and artifacts
only; it calls no provider and opens no database. It is not dataset validation.

To intentionally regenerate after inspecting a contract change, use the same command
without `--check`. An unreviewed canonical semantic change must not be hidden by rebuilding
V1: version the affected registry contract and review its allowed uses.
