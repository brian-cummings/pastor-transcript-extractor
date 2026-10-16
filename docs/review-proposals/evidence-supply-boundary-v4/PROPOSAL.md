# V4 boundary/admission repair proposal

**Proposal only — no repairs implemented, no provider calls, no execution authority.** Brian has [accepted the V3 boundary-integrity FAIL](../evidence-supply-boundary-v3/acceptance-decision-v3.md). Discovery readiness remains closed. The accepted V3 source representation and phase geometry remain the starting point; G1/G2/G3 measurement contracts remain unchanged.

Recommend the smallest repair: a source-envelope sidecar and a single enforced, typed admission boundary downstream of the unchanged measurements. Keep raw answers immutable. The sidecar supplies reporting identity and continuation to existing questions; admission prevents unsupported source/recipient credit. Neither component predicts that the model will stop making mistakes.

## Source envelope without target expansion

Maintain two coordinate systems explicitly: exact semantic roles/target and a source-derived context envelope. Every span carries source ID, snapshot hash and original character offsets. G3's act target stays exactly the utterance; G2 endpoints remain exact directed roles; the G3 relation frame remains contiguous and separate. Preserve conditions in the exact utterance. Context cannot complete an act or explanation that is absent from its specified role span.

The context envelope must retain, where relevant, the reporting introduction, original speaker, recipient identity, historical/hypothetical/quoted versus current frame, named-source introduction, and continuation that resolves quotation scope or completes an enclosing sentence. Text appears once in natural order: contiguous preceding context, exact target, contiguous following context. Do not splice remote fragments into apparent adjacency. G2's existing contiguous relation frame remains its target container; added attribution/continuation sits outside that container, not inside a silently enlarged endpoint. G3 relation-phase context may likewise preserve a reporting introduction beyond the frame without adding act fields.

The [21 exact context exhibits](context-exhibits-v4.json) propose reviewable spans from the same six frozen sources. R053 includes Joseph's introduction; R111 Bruce's imagined doorstep offer; R114 Knapp/Crosby; R076 the old Miller Hall prayer. R023 regains the Bible/story introduction. R058/R077 continuation is visible **as context** in the original fragment diagnostics; only separately versioned full-role checks can measure the completed explanation/promise. The exhibits are not inference-ready request states and are not discoveries.

Retain the accepted 6,000-character bound on a contiguous envelope. A missing introduction, ambiguous quote end, conflicting attribution or required context beyond the bound yields `unresolved_context` and no admission. Do not silently clip or infer present speech because no reporting marker was found. Source scanning is not a new ranker and does not enumerate more candidates. This iteration only prepares the fixed panel; an automatic general envelope builder is not established by authored exhibits.

## Independent provenance witnesses

A model's source/recipient answers cannot serve as their own admission authority. A witness records source identity, exact role identity, reporting scope and recipient, source-family eligibility, relevant conditions, and the source excerpt supporting each assertion. It is bound to the candidate, complete request-state hash, question/model identities, raw receipt identity and review version. Any context/target/receipt change invalidates it.

For the first implementation, witnesses come from Codex's full-source audit and an explicitly accepted, source-controlled review record. The V4 exhibits and example Booleans are **not accepted attestations**. V3 audit findings may supply source evidence but cannot certify new raw outputs. No absence-of-marker heuristic, candidate label, probability, confidence or a second phase can manufacture a witness. Ambiguous, missing, stale or conflicting support remains unreviewed and fail-closed. Brian approves the completed packet/decision; Codex prepares and audits the cases, so Brian is not assigned annotation work.

This conservative review boundary is intentional: automatic provenance resolution for arbitrary future candidates is unestablished. Later discovery-readiness must account for review supply, throughput and deferrals. This proposal cannot establish automatic end-to-end collection safety by authoring witnesses for known examples. A wrong accepted source review can still be wrong; coordinate/hash checks establish binding, not infallible human interpretation.

## Reusable invariants

| ID | Required invariant | Missing/conflicting support |
| --- | --- | --- |
| I1 — immutable identity | Snapshot, source/role offsets, verbatim condition text, request state, receipt, model and question version match the accepted review witness. | Reject stale/cross-source/cross-state reuse. Preserve raw output for diagnosis. |
| I2 — context sufficiency | Reporting identity and required continuation are supplied, complete and source-aligned. Lack of a report marker does not prove current origin. | Quarantine candidate; do not emit a positive or negative semantic conclusion from the deferral. |
| I3 — G2 source and edge admission | Actual `linked` output, a reviewed **biblical anchor**, an actual explanatory move rather than reading/citation/repetition, compatible measured source voices/stance and sufficient raw boundary are all necessary. Biblical paraphrase eligibility is source-backed; voice and source family remain separate axes. | No Bible-explanation item. Nonbiblical support stays raw/audit-only; adoption cannot turn it into Bible evidence. A Bible source alone cannot rescue R021. |
| I4 — G3 local act admission | An actual observed act is supported in the exact utterance, not narration/context; measured voice, recipient and stance agree with independently reviewed provenance; required boundary support is present. | No admitted local item. Retain raw act and reasons; never rewrite source/recipient answers. |
| I5 — G3 current-preacher admission | I4 plus supported present preacher origin, current human recipient, actual current-listener decision, actual own/adopted stance and compatible circumstance if one is claimed. | No current-preacher item. A correctly measured historical/report/hypothetical act may enter a separate reported namespace only under I4; it never falls through to the current namespace. God is not a human recipient. |
| I6 — phase/role isolation | Both phases reference the same exact utterance/roles and expected targets; binding phase contains only relevance/binding. No merging probabilities, selecting a convenient alias or strengthening an unclear act. | Reject mismatched/extra-field response. Binding cannot add or repair an act, voice, recipient or adoption. |
| I7 — typed export | A usable evidence item can only be constructed at the central admission boundary with a valid review witness and explicit namespace. Raw measurement rows and quarantine metadata are not accepted item types. All consumer/export paths, including G2, must use it. | No bypass through raw dictionaries, diagnostics, metadata-only admission or serialized replay. Product/projection remains disabled regardless of local admission. |

These are additional **consumer admission requirements**, not new measurement questions or revised meanings. The existing model may still choose wrong answers. An unknown raw field cannot be replaced by the witness's interpretation. A guard rejection is missingness/quarantine, not a measured negative. A correct raw act may remain inadmissible because the other necessary fields are withheld.

The minimal G2 admission route also requires actual, source-supported `own_or_adopted`; a reported non-adopted explanation remains diagnostic in this design. The G3 local-act route emits act facts and reporting identity only, never a circumstance-conditioned claim or current pastor credit. The specification defines every prerequisite and each route's output limits explicitly.

For generic G3, an explicit null circumstance permits generic local evidence with `not_relevant/not_bound`; it cannot claim circumstance-conditioned care. Non-null circumstance credit requires the original relevance and same-human-recipient binding decisions and source support. These dimensions cannot be inferred merely because an act exists. Reported acts may retain their supported local meaning; no present pastor credit is added by a report of past preacher speech or by general approval of a historical story.

Implementation should keep the typed admission constructor and raw schemas separate, with a controlled factory, runtime validation on serialization/deserialization, and a consumer that refuses raw/invalid/unknown-version inputs. Python types alone are insufficient. The current consumer stays held; integration must prove every local evidence export route uses this boundary before claiming I7 enforcement. No projection implementation is needed.

## What happens to the known errors

| Case | Mechanism addressed | Prevention or containment claim |
| --- | --- | --- |
| R021 | Bible citation/read content mislabeled explanation. | Reviewed edge-kind invariant I3 quarantines the false edge even with positive model output. Source-family screening alone does not prevent it. No promise of raw semantic correction. |
| R080 | Nonbiblical quotation produces a Bible edge despite preserved source introduction. | I3/I7 enforce a veto for a known extra-biblical anchor on the real G2 output path. If anchor provenance is unresolved, quarantine as well. |
| R053 | Joseph's brothers become current listeners. | I2 supplies the introduction; I4/I5 reject incompatible raw recipient even if the act is valid. Context inclusion may improve raw accuracy but is not credited as proven prevention. |
| R078 | Narrated encouragement becomes an addressed reassurance. | Retain the successful narration veto as an early block. I4/I7 also require reviewed addressed-utterance support; a new narration form not caught by the surface veto cannot auto-admit. |
| R111 | Bruce/hypothetical householder becomes preacher/current listener. | I2 preserves the frame; I4/I5 quarantine raw provenance mismatch. A future compatible reported offer could retain invitation/care/support locally, never delivery or current pastor credit. |
| R114 | Historical Knapp-to-Crosby request becomes a current-listener invitation. | I2 preserves identities; I4/I5 quarantine mismatch. Adoption is not fabricated from the automatic flag wording. |
| R076 | Historical prayer becomes present preacher voice. | I2 preserves past reporting; I4/I5 reject wrong voice/current-human credit. God/no-observed-human-act remains a required control; no prayer act is added. |

An old wrong row cannot be “repaired” into a reported item by relabeling it after audit. It remains quarantined. Only a separately valid compatible measurement can support that local namespace. No case IDs, exemplar strings or expected answers are used as guard logic.

## Deterministic specification tests

The [invariant specification](invariant-spec-v4.json) provides 55 design assertions: the seven critical-case witnesses; one supported positive per admission route; one missing prerequisite at a time; and three counterfactual correctly measured reported controls. The CLI verifies these assertions with generic necessary-condition logic, independent of model responses, and verifies exact source/context/check lineage.

These are executable **specification-consistency tests**, not an implemented guard or proof that production already enforces the design. Every example with missing provenance must deny even when model positives are maximal. All-supported witnesses must remain eligible in their declared namespace, preventing a vacuous all-deny design. Unknown/missing/non-Boolean values are never true. Reported-local eligibility is not current-preacher eligibility. No positive example is a new observed item or a semantic rescoring.

After implementation approval, focused unit/integration tests must exercise the actual central constructor and serialization/export paths with injected answers: unknown/stale witnesses; changed source/target/context/receipt; quotation and past/hypothetical/current distinctions; God/human and null/non-null circumstance conflicts; a reporting envelope containing neighboring reassurance while target is narration; nonbiblical versus biblical anchors; Bible reading versus explanation; phase swap, duplicate field, cross-alias reuse; and corrected versus incompatible reported output. Test the G2 and G3 consumer entry points end to end. A test of this proposal checker alone is insufficient for implementation acceptance.

## Versioned checks and smallest semantic revalidation

[CHECK_DESIGN.md](CHECK_DESIGN.md) and [check-design-v4.json](check-design-v4.json) propose six forward comparisons for R004/R058/R073/R077. Original V3 inputs, expectations, receipt keys, results and audit remain pinned and unchanged. R023's missing biblical context is separately retained as an envelope requirement, not silently counted as a V3 success.

Recommend implementing only the envelope fields/fixed panel materialization and central admission boundary with focused tests; retain existing representation factories and phase isolation. Then prepare a separately reviewable V4 input/criteria/authorization packet. No full-source collector, automatic attestation system, new semantic question, ranker or projection is needed for this step.

The smallest proposed semantic revalidation retains all 21 original diagnostic geometries (33 requests) with versioned V4 context and adds three complete/explicit role variants: R004 gloss, R058 complete explanation, R077 complete promise (1+1+2 requests). **Maximum 37 new requests, zero automatic retries.** R004 ambiguity, R073 gated stance and R077 fragment comparisons share base-case requests; six forward comparisons do not require six extra candidate runs. Original and forward comparisons must be reported separately. No frozen V3 record is rescored.

Use unchanged question factories, `jev-1.13.0` and original selected-option probability >= .80 gate; raw confidence remains separate. The future input must freeze exact contexts, request hashes, source/receipt-bound reviews, current pricing/preflight and a cumulative attempt/token/list-price ceiling before Brian authorizes execution. This proposal grants no run, spending or cached-receipt-reuse authority. V3 answers cannot stand in for changed V4 states. Runtime results/receipts belong under the configured application base directory.

Revalidation must audit every positive field, prepared difference and unscored failure against supplied and full-source evidence. Report **raw semantic preservation** separately from **admission containment**. Frozen V3 remains FAIL. Any new confirmed raw critical error remains a raw semantic FAIL; only a separately frozen containment criterion could accept a design with wrong raw answers if enforced quarantine holds on every real export path. Zero unsupported admitted items is necessary; positive current and reported controls and at least one discriminating G2 explanation are required so safety is not achieved by discarding everything. R092's reported-recipient/binding withholding remains an explicit limitation; containment success alone cannot claim its semantic discrimination. Unknowns, missing context, unmatched positives or untested routes yield HOLD, not an implicit PASS.

Brian should approve implementation of this narrow design only after reviewing this proposal. Semantic execution needs a later, fingerprint-bound authorization. After a scoped boundary decision, prepare a **separate discovery-readiness decision** preserving unresolved automatic discovery, opportunity denominators, review throughput, recall, recurrence and economics. The 790 V2 non-reference positives remain unaudited. Collection and pastor projection/comparison/scoring remain held.

## Review command

```sh
pte analysis evidence-supply-boundary-repair-proposal
```

Read-only: verifies the accepted FAIL, frozen inputs/code, exact source exhibits, proposed check lineage and deterministic specification assertions. It performs no inference, produces no runtime artifacts and grants no implementation or collection authorization.
