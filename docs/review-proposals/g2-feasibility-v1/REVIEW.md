# Small G2 implementation/validation proposal V1

Status: **prepared, not evaluated**. Brian approves G2 and G3 as design directions
alongside bounded G1 and selects a small G2 feasibility proposal next. The isolated
harness is ready for the exact command below; no provider/dataset validation has
been run. It is not the full G2 capability and is not connected to production PTE.
G1 implementation/expansion, G3 implementation, G4 and broader collection remain held.

## Product question and experimental scope

Can grounded semantic relations be distinguished from proximity for:

1. **One text/explanation contrast:** biblical wording actually explained versus
   reading/citation followed by unrelated claims or by missing explanation.
2. **One developed-application contrast:** a response with stated rationale,
   qualification, obstacle-sensitive guidance or concrete steps versus a command
   alone, constraint alone or unrelated nearby assertions.

Six independent facets are tested: `explains_text`, `reason_supports_claim`,
`grounds_response`, `qualifies_claim`, `specifies_response_step`, and
`addresses_response_obstacle`. Multiple facets may occur; one does not imply another.
The remaining G2 development/interpretive distinctions are out of this test's scope.
No global depth, interpretation-quality, fidelity, pastoral-quality, coherence or
pastor-comparison value is computed. A response can be concrete without a rationale;
a passage can contain rich untargeted development without proving the particular
relation between the supplied endpoints.

## Candidate-builder design

Version: `g2-source-clause-neighbor-pairs-v1`, implemented only in
[experiment.py](experiment.py), outside the production pipeline.

- Inputs are the exact saved target blocks and bounded context in [input-v1.json](input-v1.json).
  Authored cases use their complete short targets. Natural cases have **PTE-prepared
  fixed focus windows** with exact offsets into their unchanged saved targets.
  This is a deliberate local proof population, not automatic discovery of all episodes.
  [input-v1.md](input-v1.md) exposes every source, proposed check and candidate pair ID.
- Within each focus, code splits at sentence punctuation, line breaks, selected
  clause connectors and timing phrases. Exact source slices retain character offsets;
  no semantic role or edge is assigned by the builder. It proposes adjacent and
  next-nearest units in both directions, closest distance first. No pair joins clips
  from different blocks, creates invented text or supplies context-only endpoints.
- Hard bounds are 40 units and 48 pairs per case. Retained/omitted units and pairs
  are recorded. An omitted required endpoint is a candidate-coverage failure even
  if every evaluated pair is classified correctly. At preparation, all specified
  review-target pairs are represented; this is coordinate coverage, not semantic recall.
- The provider sees the full original target, context, and exact shortlisted pairs,
  so quoted frames can be resolved; it sees no proposed labels, old probabilities,
  sermon title, pastor profile, identity label or expectation rationale. Both
  relation endpoints and their semantic connection must still be supported in
  target text. Context may resolve references but cannot furnish an absent relation.
- Sentence/clause slicing is not semantic episode recovery. Every episode boundary
  remains unreviewed, and no duration or whole-episode coverage is credited.
  The separate local-sufficiency question can withhold a relation whose needed
  premise, response or referent is outside the target. None of these mechanics
  proves whole-sermon candidate recall or long-distance edge coverage.

No reviewed expected pair is directly handed to the model as the only correct
candidate. All mechanically proposed pairs in each frozen window are evaluated,
including reversed and unrelated pairs. The focus windows themselves are curated:
pass would demonstrate only this bounded local builder plus its relation judgments.
No claim of fully automatic G2 follows.

## Exact versioned TypeSafe questions and composition

Question version: `g2-local-semantic-edges-choice-v1`.
[questions-v1.json](questions-v1.json) publishes the complete provider-visible
instructions/criteria at normalized position zero. The packet pins their SHA-256;
the runner rejects drift before constructing a client. Per request, only the pair
index changes. The eight questions per pair are:

| Question | Answer options | Purpose |
| --- | --- | --- |
| Each of six independent facets | `linked`, `not_linked`, `incomplete`, `unclear` | Decide that specific directed relation and endpoint roles; topic overlap and adjacency are insufficient. |
| Voice/adoption | `own_or_adopted`, `reported`, `rejected`, `unclear` | Keep a genuine reported/rejected edge inspectable without attributing it to the preacher. |
| Local evidence boundary | `local_sufficient`, `continuation_required`, `unclear` | Distinguish enough local evidence from an omitted dependency; never certify a full episode. |

Choice is used for these **local per-facet states**, not for an exclusive sermon
style or a block-wide position. Each question is independent. A concentration of
probability on `not_linked` is not presence of a facet. The approach uses the typed
[Choice contract](https://docs.typesafe.ai/primitives/choice) and the existing
[Python SDK interface](https://docs.typesafe.ai/sdk/python/usage); PTE owns the
experimental meaning, thresholds and composition.

Decision policy: `g2-feasibility-decision-v1`. For this pilot only, the returned
choice is used when its own probability is at least **.80**; otherwise the
provisional decision is `unclear`. Choice confidence is retained but not used as
presence or a correctness guarantee. This is a conservative, explicitly proposed
review rule, not a calibrated production threshold or an inherited .70 display rule.
No tuning on this run is preauthorized.

A linked facet is listed as **provisional adopted local evidence** only when
adoption is `own_or_adopted` and the boundary is `local_sufficient`. It remains
unreviewed. Reported/rejected edges and incomplete/unclear outputs retain raw
answers and do not acquire adopted credit. These are separate facet records,
not a facet count interpreted as substantive depth.

## Fixed inputs, natural controls and reuse

The prepared packet contains **16 cases: eight authored and eight archived natural
blocks**, with 136 directed candidate pairs, **1,088 questions**, and at most
**42 uncached requests** in four-pair batches. Model is pinned to `jev-1.13.0`,
timeout 45 seconds per request, SDK retries zero. Partial reruns make fewer calls
through independent per-pair caches. No cohort expansion, model override, automatic
retry/splitting or database inference is included. Token usage is returned by the
provider, not estimated as a price/latency/accuracy claim.

| Natural video:block | Fixed saved input | Proposed control / why chosen |
| --- | --- | --- |
| 4430:25 | Source/material V1 | Quoted dark/ear wording followed by “He implies…”: genuine text/explanation candidate. |
| 1200:45 | Source/material V1 | “He gave all” → applied time-in-Scripture appeal: stated rationale/response candidate. |
| 1200:25 | Public treatment V2 | Church-citizenship prescription transitions into Alexander Graham Bell biography: deliberately proximal unrelated objects. |
| 1200:32 | Source/material V1 | Busy-life/children constraint is elaborated without a remedy: obstacle mention alone is not obstacle-sensitive guidance. |
| 4430:37 | Source/material V1 | Narrated penance advice with film/story and adoption ambiguity: no unearned preacher adoption; retain unclear rather than fabricate a gold theological stance. |
| 590:40 | Source/material V1 | Truncated Romans introduction/reading: not developed explanation of the quoted fragment; missing boundary dependencies stay visible. |
| 1200:23 | Source/material V1 | Two kingdom interpretations are adjacent: meaningful distinction is not automatically a text-anchor → explanation edge between these two endpoints. |
| 590:64 | Listener V3 | Naming missionaries/evangelism as recipients of prayer is specific guidance, not a separate rationale merely because terms are nearby. |

Natural expectations are **prepared PTE interpretations for review**, not independent
gold annotations. Ambiguous cases explicitly allow limited alternatives. PTE owns
post-run interpretation, including revising a demonstrably incomplete expectation
with recorded reasoning; any such revision cannot silently retune prompts or turn
a failed experiment into success. Brian runs and reviews a prepared recommendation,
not annotates the cases or chooses experiments.

Authored controls reuse G2-01/02/04/05/07/09/10/11. G2-09 is explicitly extended
with a second nonexplanatory target sentence so the context-only control receives
real pair questions; it is labeled an authored variant, not edited natural evidence.
The two primary contrasts include directional reversal controls. Rejected argument,
qualification binding and truncated-premise controls preserve the broader failure
modes without expanding to the full G2 relation inventory.

**Reuse audit:** exact saved source text, segment indexes, timestamps, context-builder
provenance and existing source/material/listener locator results are retained.
Old probabilities are not supplied as new relation answers or model cues. A bounded
read-only inventory check for these three videos found only existing TypeSafe topic
projection runs, not grounded `sermon-basics`/style evidence runs suitable for these
links. The packet records that absence; it does not launch equivalent collectors.
Already quoted text/reference strings remain source-grounded, not verified biblical
alignments. Additional grounded Scripture/style evidence, if later supplied, must
have pinned compatible provenance before it may supplement candidates.

All source packets are repo-local and SHA-256-pinned. No external data mount, live
membership refresh, reclassification or database is required by Brian's command.
The experiment tests archived transcript semantics and grants no current pastor
attribution or population inference.

## Exact command Brian should run

From the repository root, with the existing TypeSafe API key available to the SDK:

```bash
pte analysis g2-feasibility-review
```

**This is the provider validation command. Codex has not run it.** It reads the
fixed packet, rejects question/source drift, invokes only the eight pilot questions
per shortlisted pair, and writes:

- `evaluation/g2-binding/feasibility-v1.results.json`: raw Choice distributions,
  resolved model, input/question/cache identities, request/usage provenance,
  per-pair decisions, independent provisional facets and diagnostic checks.
- `evaluation/g2-binding/feasibility-v1.results.md`: source excerpts, prepared-check
  outcomes and every positive candidate requiring PTE interpretation.
- `evaluation/g2-binding/cache-v1/`: independently identified per-pair answers,
  reusable across request regrouping. All-hit replay constructs no SDK client.

No production registry, profile, membership, threshold or corpus is mutated.
On malformed/provider/model failure, successful pair caches remain and an
`execution-failure` JSON/Markdown companion records incomplete execution; no
partial result is advertised as a semantic pass. Brian may rerun the identical
command after the concrete execution issue is resolved.

The local preparation/integrity commands are distinct:

```bash
pte analysis g2-feasibility-review --check-only
```

Preparation and this integrity check have made zero provider calls. They verify
artifact/candidate/question reproducibility only; neither is dataset validation.

## Failure-mode classification

| Failure | Meaning and resulting action |
| --- | --- |
| Candidate omission / wrong granularity | Required reviewed endpoints are absent, overbroad or clipped; classify separately from model error. Revise only this bounded builder if justified. |
| False proximity/directional edge | `linked` is returned for unrelated or reversed endpoints; freeze the example as a semantic blocker. Do not call co-occurrence development. |
| Context leakage | A facet is manufactured from context-only explanation/reason/guidance; blocks a pass even if other contrasts work. |
| Voice/adoption error | Reported/rejected/ambiguous material receives adopted credit, or explicit adopted material is lost. Preserve raw edge and adoption decisions separately. |
| Boundary overclaim | Missing premise/response or truncated evidence becomes a complete adopted relation; blocks the affected use. A complete local decision never certifies a whole episode. |
| Qualification/obstacle misbinding | A condition or remedy attaches to a different claim/response, or constraint mention becomes guidance. Requires endpoint-specific revision. |
| Facet/role substitution | A command becomes its own reason, a distinction becomes text explanation, or specificity becomes a quality judgment. Keep facet failures separate. |
| Unclear / false negative | A supported relation is withheld under .80 or missed; retain uncertainty and diagnose semantics before changing a policy. No tuning just to cross the threshold. |
| Corrupt/incompatible/provider failure | Incomplete outputs, bad probabilities, changed sources or model mismatch. Execution failure is not evidence of semantic feasibility or lack thereof. |
| Quality/coverage overclaim | Facet counts are used as depth, fidelity, whole-episode coverage or pastor traits. The harness forbids such output; human review must reject such interpretation. |

## Proposed acceptance criteria and resulting decisions

The runner's numeric screen is diagnostic only. **PTE must inspect all linked
predictions**, not just the preselected successful pair. Extra positives are marked
unreviewed; an easy match cannot cancel another false edge on the same control.
No final PASS is computed or collection activation written by the command.

**Pass proposal:** both primary contrasts work on their authored controls and
natural positives; all required endpoints have meaningful coverage; the critical
unrelated/reversed, context-only, reported/rejected and incomplete-boundary controls
produce no erroneous adopted relations; qualification/obstacle and specificity
remain distinct; and review of all remaining positives finds no such critical
false edges. All prepared checks must match or have an explicitly documented
interpretation correction independently justified from the source. All ambiguity
must remain represented within its predeclared alternatives. This proposes a
small local semantic-edge feasibility success, not measured natural recall or
full G2 readiness.

Result: preserve this pilot evidence and propose a separately scoped next step
for the demonstrated facets, with its own inputs and coverage requirements. Do
not expand G1, implement G3/G4, aggregate a pastor profile, or start broader collection.

**Partial-pass proposal:** one contrast/facet set works while another misses
relations, abstains, lacks meaningful candidates, or fails a noncritical detail;
no unsafe false adopted edge/context leakage is being treated as usable. Name
exactly which facets and conditions are supported and which are withheld. A
critical failure in one branch cannot be hidden by the other's success; that
branch is a failure/unavailable even when the overall outcome is partial.

Result: retain reusable correct answers, prepare one narrow builder/question or
binding revision for the failed/withheld facet, and give Brian a new bounded
command only after preparing it. No automatic rerun, cohort expansion or broad rollout.

**Failure proposal:** either primary distinction is systematically replaced by
proximity, or any critical leakage/adoption/boundary false edge remains unresolved;
or an essential candidate/evidence requirement makes the current design unsuitable.
An isolated ambiguous natural case is not automatically systematic failure, but
it cannot be promoted to positive evidence. Separate technical incompletion from
semantic failure and do not declare either a pass.

Result: keep affected richer-profile fields unavailable and recommend a concrete
alternative decomposition or improved evidence scope. Leave frozen existing
measurements closed; failure is not permission to restart taxonomy development.

These are fixed proposed review criteria for a deliberately selected feasibility
sample, not statistical guarantees or calibrated error rates. Brian's handoff is
the one command above and approval/rejection of the interpreted result. Codex stops
now after preparing the proposal; provider/dataset validation remains Brian's task.

## Subsequent V1 interpretation — 2026-10-14

Brian ran the 42-request V1 packet and records **PARTIAL PASS**: the text/explanation
architecture is encouraging, while application/adoption/semantic-unit reliability
does not justify collection. [The manual A/B/C audit and single V2 revision](../g2-feasibility-v2/REVIEW.md)
now supersede this original handoff for the next run. V1 raw inputs/results/caches
remain immutable comparison evidence; do not regenerate or overwrite them to
record the interpretation. The V2 command is explicitly `--revision v2`.
