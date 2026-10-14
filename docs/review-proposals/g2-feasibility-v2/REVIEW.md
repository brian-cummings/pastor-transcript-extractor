# G2 partial pass: one bounded error-analysis/revision cycle

Status: **V1 PARTIAL PASS, as Brian's 2026-10-14 decision; V2 prepared, not run**.
Continue investing in the local semantic-edge representation, without production
collection, expansion or abandonment. G1 implementation/expansion, G3 implementation,
G4 and broader collection remain held. This is one cycle, not a new optimization series.

## Manual adjudication, before question revision

[The complete audit](audit-v1.md) assigns every one of the **ten displayed mismatches**
to exactly one primary bucket. [audit-v1.json](audit-v1.json) retains the original
check, source pair, probabilities, decision and proposed action. It also reviews
**all fifteen linked facet cells**, including unscored extra positives. V1 inputs,
results and caches remain unchanged and fingerprint-pinned.

- **A — contract/expected-label/reporting problem: six displayed mismatches.** The
  timing fragment in a single command is an intrinsic detail, not a second guidance
  utterance. Scoping the speaker's distinguishing activity does not necessarily
  qualify the explained claim. Reported origin and explicit rejection are both true.
  Several top-ranked negative answers became `unclear` under .80: that is withholding,
  not a demonstrated wrong edge. Overbroad text-role endpoints can also be ambiguous.
- **B — candidate/boundary problem: two displayed mismatches.** “He gave all” lost
  the rhetorical bridge “why shouldn't we?” inside its reason endpoint. A caption
  newline separated “pray for our” from “missionaries,” producing grammatical fragments.
  Substring coverage was 100% for review targets but semantic-unit adequacy was not.
- **C — judgment problem: two displayed mismatches.** The five-minute-call method
  is clear but under-discriminated; the stated benefit of that call is weakly bound.
  Neither is demonstrated to be a wrong high-confidence adopted belief: linked is
  top-ranked on the step, and adoption is top-ranked own, but probabilities do not
  clear the proposed .80 rule. They remain real measurement withholding on clear cases.

The positive-cell audit finds six additional concerns: wrong endpoint roles,
condition/rationale ambiguity, an incomplete premise bundle, and causal reasons
classified as qualifications. Some are already safely unadopted reported material,
but their raw semantic kinds still need correction. The unscored adopted
`grounds_response` on Scripture → explanation is not a valid response edge merely
because the text contains an imperative. Text explanation success cannot hide it.

**Adoption correction:** G2-04/G2-05 did not produce confident reported/rejected
attribution; own was top-ranked at .60/.78 and withheld. G2-10 recognized the quoted
argument and returned reported at .80, already withholding adopted credit. The
failure is that its one field cannot preserve both reported origin and explicit
rejection. Do not describe these as three instances of quoted claims becoming pastor traits.

## Narrow revision decisions

### 1. Clarify four relation questions; preserve two successful facet questions

- `specifies_response_step`: a **distinct** concrete guidance utterance specifying
  the same action's method/initial step qualifies. “Start with a five-minute
  conversation” can develop a prior request to call; a procedure with many steps is
  unnecessary. Splitting “today” from one directive does not manufacture a second
  instruction or relation. Intrinsic detail belongs to a future node representation.
- `grounds_response`: the second endpoint must actually request a lived response,
  including a reported request whose stance is recorded separately. A descriptive
  explanation is not itself a response. A stated anaphoric benefit can supply
  rationale after the request. A conditional guard alone is not the separately
  stated motivating reason/benefit; obstacle mitigation remains an independent facet.
- `reason_supports_claim`: require a stated premise and the particular teaching or
  normative assertion, not automatically a conditional setup plus imperative.
  A clear rhetorical normative conclusion may count; voice/adoption stays separate.
- `qualifies_claim`: distinguish conditions/exceptions/applicability restrictions
  from causal explanations, and claim scope from the scope of explaining it.
  “Because this is a big sin” is not automatically a qualification in both directions.

`explains_text`, `addresses_response_obstacle`, and the local-boundary question
remain byte-identical to V1. Their exact answers are reused for unchanged pairs.
All six facets remain independent. No count becomes depth, correctness or quality.
The **.80 decision threshold stays unchanged**; no near-cutoff answer is tuned upward
or retroactively normalized into certainty.

### 2. Separate voice origin from preacher stance

V2 records `left_voice`, `right_voice`, and `adoption` independently of relation
existence. An utterance can be the preacher's own speech even if it expresses no
second guidance statement. An argument can have reported origin and be explicitly
rejected. Rejection is never synthesized into an affirmative opposite belief.

Endpoint voice options: preacher, quoted/reported, mixed, unresolved. Source-stance
options: own/adopted, unadopted report, explicit rejection, unresolved. Low-confidence
choices retain `unclear`. A proposed adopted facet still requires linked relation,
own/adopted stance and local sufficiency; raw provenance records do not themselves
create a pastor characteristic.

This is the reusable **source-voice versus stance design** needed by G1/G2/G3,
validated here only inside the bounded G2 pilot, once per pair rather than once
per facet. It does not implement or expand G1/G3 or establish that the cross-cutting
problem is empirically solved. Their approved contracts can later consume a
validated envelope rather than independently invent incompatible adoption meanings.

### 3. Preserve all frozen cases/pairs, add only bounded repair candidates

Every original target, context, focus and all 136 V1 pairs remain. Four adjudicated
cases receive source-backed overlays: complete conditional guidance (G2-05), the
joint forgiveness/trust premise sentence (G2-07), the intact rhetorical reason
(natural-1200-45), and wrapped imperative clauses with complete objects
(natural-590-64). All old fragmented pairs remain visible as regressions. The
wrapped sibling prayer requests are also a new explicit negative rationale check.
No full-sermon candidate builder or more distant-context expansion is introduced.

Only **five authored cases** are added, with no new natural sermons:

| Addition | Narrow justification |
| --- | --- |
| Step positive: call → start with a five-minute conversation | Distinguish a real method/initial step from the ambiguous wording of the original positive. |
| Step negative: call → office meeting lasts five minutes | Same duration vocabulary, wrong action/object. |
| Qualification positive: call → this invitation applies only if contact is welcome | Explicit scope of that invitation rather than scope of explanation activity. |
| Qualification negative: call → church office opens only on weekdays | An unrelated restriction must not attach to the response. |
| Same reported argument, “reporting without endorsing,” without rejection | Isolate reported origin from rejection stance against frozen G2-10. |

The prepared packet has **21 cases, 170 pairs**. Original recorded targets and
expectations are preserved in the audit; V2 expectation amendments are explicit.
Where an unclear negative control is admissible, it is **unresolved non-evidence**,
not a confirmed correct negative or evidence that reliability improved. Clear
primary controls must still discriminate. G2-07 and natural-1200-23 cannot alone
supply a pass by being relabeled uncertain.

## Exact questions, reuse, and budget

Question version: `g2-semantic-edges-and-independent-voice-v2`.
[questions-v2.json](questions-v2.json) contains all ten exact questions at normalized
position zero. [input-v2.json](input-v2.json) pins questions, the manual audit,
V1 input/results, cases, repair pairs, controls and question budget.

- **408 V1 question answers are reused**, only when full source state, pair,
  model and complete per-question semantics are identical. Their original request
  provenance and source question digest/version remain attached.
- At most **1,292 new question answers and 52 uncached provider requests** are
  possible, in the same four-pair batching, pinned model and zero-retry policy.
  New framing and necessary repair controls add work; this is not advertised as
  cheaper than the first run. Cache reuse avoids recollecting unchanged judgments,
  not a cost-pruning experiment.
- V2 stores independently keyed per-question answers, reusing exact hits without
  constructing a provider client. No original raw probability, question cache,
  threshold, classification/profile membership or collection policy is overwritten.
- Baseline serialized distributions summing to .99 are checked with V1's .01 mass
  tolerance plus floating-point epsilon. The probabilities are not renormalized
  and the semantic .80 rule is not altered.

No additional model, topic, role, Scripture, style, G1 or G3 inference is requested.
No candidate pruning/batching optimization is mixed into this semantic revision.

## Exact rerun command for Brian

With the venv active, from the repository root:

```bash
pte analysis g2-feasibility-review --revision v2
```

**Codex has not run this provider/dataset validation command.** The prepared artifact
check is separate and provider-free:

```bash
pte analysis g2-feasibility-review --revision v2 --check-only
```

Results go to `evaluation/g2-binding/feasibility-v2.results.json` and `.md`, with
pending-interpretation status, original raw V1 comparisons, corrected expectation
checks, per-question reuse/request provenance, independent facet decisions and
endpoint voice/source stance. The complete source text and every linked prediction
remain available for manual interpretation. Successful partial request caches are
retained on execution failure; no partial run is declared a semantic success.
V1 remains reproducible with the default command/`--revision v1`.

## Interpretation and one-cycle stopping rule

After Brian runs V2, PTE development will inspect **all** new linked cells, stance
and boundary outputs, not just prepared matches. The original and completed-endpoint
pairs must be compared separately; matched substrings do not prove a good semantic
unit. Each remaining substantive error goes into A, B or C again, with raw probabilities
and withholding distinct from an adopted false edge. No scalar accuracy or global
facet score replaces that review.

- **Feasible for the bounded architecture:** clear text/explanation and developed
  application positives discriminate from their unrelated/reversed controls;
  explicit method and direct qualification controls work; quotes/rejection and
  context-only evidence acquire no adopted credit; no systematic wrong role,
  causal-as-qualifier or incomplete-premise edge remains. Residual uncertainty is
  concentrated in identified genuinely ambiguous/decomposed cases. Record only the
  scoped feasibility finding; then recommend preparing bounded G3 under a separate
  concrete handoff, rather than extending this into endless G2 optimization.
- **Partial pass persists:** named facets remain useful, but a clear method/rationale,
  qualification or source-stance distinction is still weak. Withhold the failed
  facets/conditions and state whether the architecture supports moving to G3 while
  retaining those gaps. Do not automatically open another G2 tuning cycle; provide
  the interpreted decision for Brian.
- **Not feasible for the affected use:** clear wrong-object, context-leakage,
  adopted-report/rejection, or systematic semantic-role/edge failures persist.
  Keep affected profile characteristics unavailable, propose a concrete alternative
  evidence decomposition, and seek the resulting decision before more inference.
- **Execution failure:** malformed, incompatible or partial provider output is not
  a semantic outcome. Preserve successful caches and report the concrete execution
  issue; do not relabel infrastructure problems or lower certainty thresholds.

No outcome authorizes production collection, broad G2/G1 expansion, G4, or a quality
score. This handoff performs the requested single analysis/revision cycle and stops
before Brian's provider run. Cost optimization remains deferred until semantic soundness
is established, as requested.
