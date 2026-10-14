# G2 V1: text, argument and application development

Status: **approved as design direction**, alongside bounded G1 and G3. The
[small G2 feasibility proposal](../g2-feasibility-v1/REVIEW.md) is now prepared;
it implements only an isolated pilot harness, not this full capability.
G1 implementation/expansion is on hold. This adds no collector, question pack,
provider invocation, projection implementation, or quality score. G4 stays deferred
and should reuse G1 claims and G2 relation evidence.

The product question is: **How does this pastor develop a text, an explanation,
an argument or a lived response?** Different pastors may affirm similar positions
and demonstrate very different treatment. G2 should preserve those differences
without translating verbosity, citations or doctrinal presence into depth.

## Downstream statement contracts

| Desired characteristic | Target pastor-level understanding | G2 contribution and remaining limit |
| --- | --- | --- |
| C06 Application development | What responses are developed, why, for whom, with what steps, circumstances and obstacles? | Ground response–rationale–guidance links and addressed constraints. Not compliance, effectiveness or the pastor's private behavior. |
| C10 Scriptural engagement | How do biblical texts carry explanation, argument or application? | Bind a stated text/passage to the specific explanation, reason, conclusion or application it is used to support. Not citation frequency or interpretive fidelity. |
| C11 Interpretive tendencies | What interpretive operations are actually demonstrated, rather than merely professed? | Preserve source-grounded operations and text/reasoning links: wording, immediate context, genre, textual argument, cross-text connection, textual-to-listener application. These are proposed operation distinctions, not imposed schools of interpretation. |
| C13 Depth of treatment | In what subjects does the pastor develop reasons, distinctions, qualifications, alternatives and implications? | Preserve a profile of development facets plus linked episode evidence for human review. Facet presence supports descriptive development tendencies and candidate discovery; it does not certify substantive adequacy or a global depth rank. |

Permissible future wording: “In the reviewed grief passages, this pastor develops
application with a rationale, concrete steps and an acknowledged obstacle,” or
“Across these independent sermons, textual explanations repeatedly appeal to the
passage's immediate context.” Missing recurrence permits only “this passage contains…”
Missing binding permits a located passage, not a claim that Scripture carries the argument.
A developed but flawed explanation can contain observable facets; its correctness
and adequacy require separate review. The desired richer C13 field remains incomplete
without that assessment rather than being filled with an average of facet counts.

## Collection contract: observations within one sermon

Input: exact source-backed target text, actual segment/time identifiers when available,
bounded context and context diagnostics, code-owned candidate spans for episode,
text anchors, teaching statements, responses and possible relation endpoints. Existing
`H:*`, `L:*`, `M:*`, detected Scripture references/alignments and grounded style spans
may supply candidate locations **with their original provenance**, not semantic labels
for new G2 relations. No pastor profile, prior characterization or expected score is input.

Output: an `EpisodeCandidate`, source nodes, evidenced relation/operation records and
explicit unresolved fields. A candidate episode is a proposed local treatment unit,
not a reviewed complete run or a measured duration of depth. G2 and G3 can share an
episode ID while retaining different observables; shared spans do not multiply evidence.

| Record | Required fields and meaning |
| --- | --- |
| EpisodeCandidate | `episode_id`, source target ID/hash, source bounds, subject candidates, completeness (`local_complete`, `partial`, `unknown`), proposed-boundary status, continuation diagnostics. No automatic entire-sermon episode. |
| EvidenceNode | `node_id`, exact source span, role (`text_anchor`, `teaching_statement`, `reason`, `alternative`, `qualification`, `implication`, `listener_response`, `guidance`, `obstacle`), voice/adoption and reference status. A node's role is an observation needing evidence, not assigned by a keyword. |
| DevelopmentRelation | `relation_id`, episode ID, typed relation, endpoint node IDs, exact target evidence of their relation, voice/adoption, scope, stated qualifications, status (`supported_observation`, `unresolved`), unresolved reason. Node co-occurrence is insufficient. |
| InterpretiveOperation | Operation ID, proposed operation kind, text/claim nodes, exact evidence of the performed operation, demonstration versus reported/self-described method, voice/adoption, review status. Keep “operation observed” separate from “interpretation correct.” |
| Production envelope | Actual source segment/time/text hashes, context roles, eligibility/membership, candidate-builder/question/model identities, raw typed answers, grounding and semantic-review status. Authored examples omit model answers and fabricated real sermon IDs. |

**Proposed development relations** are separate observations, not exclusive style labels:
`explains_text`, `reason_supports_claim`, `distinguishes_concepts`,
`addresses_alternative`, `qualifies_claim`, `works_out_implication`,
`grounds_response`, `specifies_response_step`, and `addresses_response_obstacle`.
Some are facets of explanation, some of application; do not sum them as if they were
commensurate points. An explanation need not display all nine. Multiple nodes and
relations may occur within a target, including parallel reasons or different responses.

`grounds_response` binds a response to its stated reason/claim/text. A command can be
concrete without a stated rationale; then `specifies_response_step` may be observed
while grounding is unobserved. “Because” alone does not establish a substantive reason;
the exact semantic relation must be supported. Similarly, “some say” alone does not
establish engagement with an alternative: a response to the alternative is required.

A citation/quotation/retelling is a `text_anchor` candidate. To observe `explains_text`,
the target must actually explain that text's meaning, context, argument or implications.
A Scripture reading followed by an unrelated assertion is not an explanatory edge.
A stated cross-text link must include evidence of the connection, not two references.
An explanation without a detected citation can be retained with an unverified textual
anchor and a limitation; detector silence does not veto genuine textual explanation.
G2 does not validate a quote against the Bible or decide whether an interpretation is faithful.

### Evidence scope and reuse of G1

Assertions and operations must occur in target evidence. Context can resolve a passage
name or referent but cannot provide the missing explanation, reason, step or obstacle.
For the initial contract, both semantic endpoints and their relation must be target-grounded.
A relation depending on a premise supplied only by context is `continuation_required`,
not a fully observed argument. Preserve any independently supported local facets.

Future cross-block linking would require each endpoint to be independently target-grounded
in an eligible retained source block, plus explicit relation evidence and a separately
versioned linking rule. Promoting context-only text into evidence is not that rule.
Until such a rule exists, truncation constrains episode characterization and negative claims.
Do not expand the frozen context windows or label whole runs complete to hide this gap.

Where compatible G1 claim/voice/qualification records exist, reference them by ID. G2
can use a local source-backed teaching statement before G1 exists; it does not require
normalizing every statement into a systematic theological predicate. G1's assurance/public
vocabulary is not enlarged by this design. G2 adoption is local evidence, not pastor belief.
Reported or rejected arguments remain inspectable material and must not be projected as
the preacher's demonstrated reasoning unless independently adopted. An applied biblical
command needs evidence of its present listener application rather than quotation alone.

## Missingness and abstention

Preserve `not_observed_in_complete_candidate`, `unresolved_binding`,
`continuation_required`, `unresolved_voice`, `candidate_coverage_unknown` and
`not_evaluated`. Absence of a facet in a short or partial window is not superficiality.
A missing alternative is not refusal to consider alternatives. An unclear text anchor
blocks the particular text-bound claim but need not erase observed nontextual reasoning.
An unverified anchor must not become a specific verified passage citation.

Separate transcript/model uncertainty from any uncertainty stated by the preacher.
If a facet/operation is mentioned only as a habitual self-description (“I always study
context”), record a method statement candidate; it does not establish demonstrated
context reasoning. TypeSafe collection may select/judge grounded candidates with narrow
independent questions; it must not answer “is this pastor deep?” or “what is their usual method?”
No threshold, API integration, candidate recall or semantic accuracy is established here.

## Projection contract

1. Keep source nodes, relations, performed operations and proposed episode boundaries
   separate. Review boundaries and independence before computing episode counts or duration.
   Repeated blocks/uploads do not manufacture recurring explanatory patterns.
2. Summarize independent sermons first. Declare a whole-measured-sermon denominator and,
   where meaningful, a separately defined opportunity denominator: explanation opportunities
   for text operations, developed-treatment episodes for development facets, or listener
   response opportunities for application facets. Opportunity detection is itself required;
   selecting only facet-positive passages cannot estimate the rate of opportunities served.
3. Keep facets as typed nullable distributions/occurrence summaries with source links.
   Do not convert unobserved/unevaluated facets to zero, average citation density into depth,
   or normalize all facets into a pastor-quality score. Comparisons need compatible subjects,
   treatment purpose, windows and opportunity definitions.
4. Require coverage, independent recurrence and series/period sensitivity for statements
   about tendencies. No universal N is approved. Different treatment for different listeners
   or subjects is conditional variation, not inconsistency. Preserve changed patterns only
   with adequate dated support; do not infer sermon dates from upload dates.
5. Human review determines whether a developed explanation/application is substantively
   adequate and noteworthy for its purpose. A facet record is evidence for that judgment,
   not its replacement. C13 can show observed development patterns plus unavailable assessed
   depth; C10/C11 can show performed operations with correctness/fidelity explicitly unassessed.

A downstream discovery card can cite developed examples and explain the facets that surfaced
them. A recurrent pastor candidate requires the same coverage and uncertainty rules as
other profile claims. G4 may later reuse `reason_supports_claim`, qualifications, alternatives
and G1 propositions to inspect coherence; G2 does not compute a coherence verdict.

## Prepared contrasts and the remaining design limits

[G2 cases in CASES.md](CASES.md#g2-cases) cover text explanation versus adjacent quotation,
reason versus bare assertion, real distinction versus elaborate vocabulary, developed
application versus command-only, alternative engagement, contextual leakage, reported/rejected
reasoning, truncated arguments and self-described versus demonstrated methods.
Expected structures in [cases-v1.json](cases-v1.json) are authored design proposals.
Their span integrity is locally checkable; semantic correctness and automatic recall are not.

The design supplies missing **information types** for C06/C10/C11/C13. It does not finish
quality assessment, episode coverage, sufficiency, or validation. These unresolved requirements
must remain visible in a future profile; no declared facet substitutes for them.
