# G1 V1: bounded proposition-binding proof design

Status: **bounded design direction approved; implementation/expansion on hold**.
The [joint G1/G2/G3 design review](../g2-g3-v1/REVIEW.md) now precedes any
implementation/validation selection. Brian approved
C01–C20 and D01–D06 as design direction and authorized this bounded G1 exercise.
He did not authorize broad doctrinal expansion. G1 is first as a proof of reusable
binding, not highest priority for the whole product. **Design G2 and G3 before
expanding G1 across theological topics**, regardless of this proof's outcome.

The [desired profile](../../PASTOR_PROFILE_GAP_ANALYSIS.md) remains the product
specification. The [59-signal registry](../pastor-contracts-v1/REGISTRY.md) remains
unchanged. This increment designs collection semantics and example outputs; it
implements no collector, invokes no provider, makes no measured pastor claims,
and starts no corpus collection or clustering.

## Two bounded questions and the pastor understanding they should support

| Question | Desired eventual pastor statement | Current supply / precise missing information |
| --- | --- | --- |
| Assurance: what is said about knowing present acceptance, possible loss, and retention, with what qualifications? | Within a specified corpus/period, the pastor affirms/denies/qualifies a specified assurance proposition; mixed evidence or explicit uncertainty remains visible. | `S:assurance_security` locates treatment; it cannot determine proposition, polarity, adopted voice, condition, or uncertainty. |
| One public proposition: does the preacher support, oppose, or prescribe a city requirement for ramps in new public buildings? | Within a specified corpus/period, the pastor supports/opposes/prescribes this specified requirement under stated conditions; no broader platform or ideology follows. | `P:critical`, `supportive`, `prescriptive` and related functions locate evaluations, but cannot bind them to this object/proposition or voice. |

The public proposition is a **synthetic policy example**, drawn from the existing
[authored public-treatment probe](../../../src/pastor_transcript_extractor/data/public-life-treatment-probes-v1.json).
It is not a real ordinance, a legal judgment or an assertion about a pastor.
Other policies in contrast cases remain out of scope; their spans are retained as
scope diagnostics rather than forced onto the ramp proposition. The assurance
predicates below are bounded proof vocabulary, not an approved systematic theology.
No denomination, eternal-security label or global pastor stance is collected.

The proof asks whether one evidence structure preserves the needed distinctions
across both subjects. It must make the information available, not simply add more
positive-presence scores.

## Sermon-level collection contract

**Input:** one exact target block and its source identifiers/character bounds;
existing bounded leading/trailing context with context diagnostics; a fixed
proof-vocabulary version and explicit object candidates. Source segment identity,
content hash, eligibility and reviewed membership are envelope provenance. No
pastor profile, prior beliefs, cross-sermon evidence or ideological label is input.
These authored cases use character offsets rather than fabricated real segment IDs;
production integration would resolve actual segment/time provenance separately.

**Output:** zero or more `BoundClaim` records, plus explicit non-characterization
and out-of-scope diagnostics. Preserve all supported claims in one target, including
qualified claims, reports, questions and opposing statements. No single block-wide
Choice decides the pastor's overall position. Within a claim, finite alternatives
may be exclusive only for that exact candidate, voice and relation.

| BoundClaim field | Meaning / grounding |
| --- | --- |
| `claim_id`, `case_id` | Code-owned IDs within one target; identity is not inferred by a model. |
| `subject_id` | `salvation_acceptance` or `city_ramp_requirement` in this proof; unresolved referents abstain. |
| `relation` | `acceptance_knowable_now`, `loss_possible`, `retention`, `public_support`, `public_opposition`, or `public_requirement`. These are distinct relations, not one ideological spectrum. |
| `polarity` | `affirmed`, `denied`, or `unsettled` relative to that relation. Opposing a requirement is affirmed `public_opposition`; denying opposition is not support. |
| `expression` | `assertion`, `question`, or `open_issue`. A rhetorical question alone does not establish affirmation or expressed uncertainty. |
| `voice` | `preacher` or an explicitly identified reported speaker; unresolved voices stay unknown and block adoption claims. |
| `adoption` | `own_assertion`, `explicitly_adopted`, `reported_not_adopted`, `explicitly_rejected`, or `undetermined`. A reported proposition keeps its voiced polarity when rejected; rejection is not silently normalized into its opposite. |
| `claim_span` | Exact target source span containing the proposition/expression; cannot come only from context. |
| `binding_evidence` | One or more grounded spans supporting voice, adoption, relation/object binding; context spans may resolve the target's referent only. |
| `subject_evidence` | Exact target/context phrase establishing the subject/object; no keyword-based invention of an unnamed policy. |
| `conditions` | Source phrases attached to this claim, tagged `condition` or `exception`. Preserve explicit connective and wording; do not infer necessity/sufficiency or unmentioned conditions. |
| `epistemic_status`, `epistemic_evidence` | `expressed_uncertainty` only with actual uncertainty language; otherwise `not_stated`. This is the speaker's expression, not model confidence. |
| `scope_text`, `scope_evidence` | Source wording and its exact supporting span about present/time/person/circumstance where stated, otherwise null. Unstated scope is unknown, not unrestricted or permanent. |

Production observation envelopes must additionally retain independent raw typed
judgments/probabilities, requested/resolved model, complete question/candidate/state
digests, actual source segment/time bounds, input context-builder version and
review/grounding status. The fixture outputs below are **authored expectations**,
not fabricated provider answers or confidence values. They do not populate those
production fields or enter the frozen measurement registry.

The per-field expected span is a binding constraint, not merely a citation to a
paragraph containing useful words. A nearby condition about another claim must
not attach to this one. Context can identify what “that requirement” refers to;
it cannot supply endorsement when the target only says “let us continue.”
An empty condition list means no condition was identified in this target candidate,
not an unconditional doctrine or policy across the sermon or corpus. If condition
binding is ambiguous, retain that diagnostic rather than silently dropping it.
A target assertion referring to context may be recorded with explicit context
provenance; a context-only assertion cannot become a target observation.

### Uncertainty and non-characterization

Return abstention/diagnostic reasons independently for unresolved subject,
relation, voice, adoption or qualification binding; retain supported fields.
`no_in_scope_claim` means no supported claim in these two bounded vocabularies,
not no theology or no public position. `candidate_coverage_unknown` means the
candidate inventory may have omitted a claim; it is not a negative observation.
Out-of-scope spans, unresolved fields and unobserved production coverage must
never become pastor-profile zeros. A clear reported claim can be recorded even
when the pastor's adoption is unresolved.

`unsettled` polarity is for an expressed unresolved issue or an unanswered question,
not a middle theological belief. An unanswered question without uncertainty
language keeps `epistemic_status: not_stated`. Whether the preacher actually holds
an uncertain overall view is a later projection question.

## Proposed TypeSafe decomposition, not a deployed integration

Recommendation: grounded candidate selection and narrow judgments composed in
code, rather than free-form pastor-stance generation. This follows TypeSafe's
[pre-parsed value-selection pattern](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook)
and [Choice contract](https://docs.typesafe.ai/primitives/choice): typed decisions
can select available candidates, but cannot select missing ones. This PTE design
must separately establish candidate coverage and semantic binding.

1. Code constructs source-backed sentence/clause and bounded multi-sentence
   candidates, retaining exact source IDs and explicit object/condition candidates.
   The present packet authors these spans to test the desired output; it does not
   prove an automatic candidate builder. Regex/sentence segmentation alone is
   not accepted as an exhaustive claim detector.
2. For each candidate, ask independent narrow questions: does the target express
   an in-scope relation; which subject and relation; what voiced polarity/expression;
   who voices it; what adoption is evidenced? Include no-match and unresolved
   alternatives. Separate claims remain separate candidate IDs; never force one
   alternative across all claims in a block.
3. Bind candidate conditions, exceptions and epistemic phrases to the particular
   claim with separate semantic judgments. References to other claims are explicit
   negatives. If claim selection is needed to construct binding state, use a later
   request; judgments in one request cannot use one another's results.
4. Code validates bounds and source identity, assembles all compatible records,
   rejects inconsistent/unsupported combinations, and exposes unresolved fields.
   Coordinate-span validity is not semantic proof. Retain raw answers and input
   candidates with their independent version identities; changing downstream
   projection never rewrites them.

Example narrow question contracts (provider syntax/model not yet selected):

| Judgment | State and permissible decisions | Important boundary |
| --- | --- | --- |
| Subject/relation | Exact candidate text and referenced source/context candidates; finite proof IDs plus `no_match`/`unresolved`. | Mere assurance/public topic vocabulary is not a proposition about the requested relation. |
| Polarity/expression | The exact relation candidate; affirmed/denied/unsettled and assertion/question/open issue. | “Does not oppose” denies opposition and cannot establish support. “Can it be lost?” has no asserted answer. |
| Voice/adoption | Candidate plus exact attribution/adoption-frame candidates; finite voice IDs and adoption alternatives. | Reported support is not preacher support. Rejected quoted denial does not itself become an affirmative loss claim. |
| Qualification binding | One selected claim and one grounded condition/exception candidate; independent yes/no binding judgment. | Only the condition actually modifying this claim attaches; preserve literal connective, not a theological causal theory. |
| Expressed uncertainty | Claim plus explicit uncertainty candidate; yes/no and grounded candidate selection. | Model uncertainty and lack of evidence do not establish expressed pastoral uncertainty. |

No production threshold or error tolerance is invented here. Raw distributions,
semantic errors and abstention must be reviewed under the future bounded validation
contract before any operational decision rule. The existing `.70` display policies
and salvation observation thresholds do not transfer to this new capability.

## Projection contract: what later aggregation may do

The ultimate target is a scoped position/qualification account for C03/C08, with
C20 expressed uncertainty as a separate characteristic. This proof does not compute
it. Later projection uses reviewed attribution and independent teaching occasions,
not counts of clauses or duplicate uploads. It must require claim-specific opportunity,
coverage and recurrence, including dated/series support where needed.

Keep a structured distribution/list of the specified claims and conditions. Compare
only matching relation, object, conditions and scope. “Knowable now” does not establish
permanent security; `retention` conditioned on trust is not silently converted into
loss mechanics; support with an access-equivalence condition is not unconditional
support for any ramp ordinance. Rejection/reporting evidence remains distinct from
adopted assertion. Explicitly adopted reports can support an observation of adoption;
plain reports cannot support the pastor's position.

Opposing assertions in one sermon are preserved as an apparent tension for review,
not resolved by vote or transformed into a career-level mixed stance. Review may
identify different voices, scopes or conditions. Unknown dates prohibit a temporal
change story. Adequately repeated, matching, grounded adopted claims can eventually
support a qualified scoped statement; inadequate recurrence or missing opposing-claim
coverage requires observed-only wording or abstention. “No contradictions found”
is bounded by the proof's vocabulary/candidate coverage, not a coherence certificate.

Human descriptions and later numeric representations must use these same bound
records. No family-wide belief average, ideology score, assurance score or opaque
quality value is permitted. A proof success permits consideration of reuse in G2/G3,
not expansion to the rest of the theological inventory.

## Prepared proof and the completion criterion

[CASES.md](CASES.md) contains 20 short authored cases with exact target/context,
expected record distinctions and reasons; [cases-v1.json](cases-v1.json) contains
source hashes, bound spans and expected structures. Cases cover affirmation,
denial, conditional retention/loss/support, report/adoption/rejection, questions,
expressed uncertainty, context-only exclusions, referent resolution, different
objects and opposing assertions. Source spans are deliberately prepared; no new
natural sermon selection, annotation or JSON work is assigned to Brian.

The local checker verifies structural integrity and reproducibility only. It
**does not prove candidate recall, semantic accuracy, routing coverage, cross-sermon
sufficiency, or the reusable capability's empirical success**. The deliverable here
is a concrete, reviewable binding contract and proof specification.

Before any eventual dataset/provider validation, development must prepare a separate
bounded harness, fixed questions/candidate builder, default natural controls, exact
command and proposed acceptance decision. Brian executes that command; development
interprets outcomes. Authored expected outputs must not be treated as model results.
Semantic review must cover each distinction separately; a single overall match
rate cannot hide systematic polarity, voice or condition failures.

Brian approves this proof specification as design direction and holds further G1
work while G2/G3 are designed and reviewed alongside it. After any future bounded proof is
reviewed (and after any separately authorized implementation/validation), **design
G2 text/argument/application development and G3 observable pastoral address before
expanding G1 to additional theological topics**. A failed G1 proof calls for a
narrow revision, not an unbounded doctrine project. Broad G1 expansion remains
unauthorized, and the consumer acceptance packet and broader collection remain deferred.
