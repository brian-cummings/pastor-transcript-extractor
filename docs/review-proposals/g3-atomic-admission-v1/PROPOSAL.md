# G3 atomic-act sufficiency and admission proposal A1

Authority update, 2026-10-15: Brian subsequently authorized implementation and provider-free replay together. See [implementation](IMPLEMENTATION.md) and [completed source audit](source-audit-a1.md). The proposal and JSON below are preserved as historical design, not current authorization.

**Recommendation: approve a small, prospective admission-policy implementation and a provider-free replay of the existing V4 receipts, after reviewing this proposal. No new model experiment is needed. Neither step is authorized by this document.** This is an admission-policy version, not Collector V5 or a semantic-contract revision.

Brian has accepted **V4 raw semantics FAIL / containment HOLD** in the [separate gate decision](../evidence-supply-boundary-v4/acceptance-decision-v4.json). Preserve all seven critical raw fields across six cases, both supported G2 admissions and all 22 quarantines. The historical audit and delegated source-review acceptance remain unchanged. This proposal cannot produce a retrospective V4 PASS.

The [JSON packet](proposal-a1.json) binds the frozen input, receipts through their source audit, review authority, decision, questions and implemented guard. It contains a design-only assessment of all 24 cases, including two proposed claim-sufficiency exhibits. These exhibits are **not accepted admission authority**. No admission repair, new consumer, new witness acceptance or semantic execution has been implemented.

## What the interface currently requires

The frozen G3 question asks:

> Is enough local target treatment supplied to judge this utterance and circumstance connection? Context cannot supply omitted address. This does not certify complete episode boundaries.

Its `local_sufficient` option means enough local evidence to decide, including definite absence of address or binding. The act questions independently ask whether the exact utterance expresses each act, independently of adoption and circumstance binding. The actual V4 guard nevertheless requires `boundary=local_sufficient` for every G3 export. Its minimal item contains observed acts and measured source/recipient/adoption, with `circumstance_claim=None`.

There is a scope mismatch: the shared question combines utterance sufficiency and circumstance-connection sufficiency, while this item asserts no circumstance connection. It is **not** an episode-completeness requirement. Nor does the mismatch establish why Jev withheld: R018 has no circumstance at all and still withholds. Separating the admission obligations is justified by the exported claim, not by guessing what a low probability means.

All 13 G3 boundary decisions are gated `unclear`. Ten raw argmaxes favor `local_sufficient` at .51–.67; three favor `continuation_required` at .56–.61. None passes .80. These are not positive sufficiency decisions. Confidence and argmax do not replace the selected-option gate.

## The two source-supported controls

| Control | Exactly supported local facts | What stays unresolved or excluded | Actual V4 outcome |
|---|---|---|---|
| R018, source 1200, utterance [30207,30249) | “Are you willing to surrender all to Christ”: challenge and invitation, preacher voice, current listeners, own adoption. Supplied envelope [30183,30394) starts “this is the call today.” | No circumstance, conversion outcome or delivery/effect claim. Neighboring Bible-study invitation is not imported. | Quarantined solely for boundary withholding: raw `local_sufficient` .64. |
| R053, source 4050, utterance [37591,37643) | “do not therefore be grieved or angry with yourselves”: reassurance and challenge. Envelope [37063,37940) identifies Joseph speaking to his brothers. Measured reported voice, reported recipient, `not_adopted_report` agree. | Measured relevance/binding remain unclear. No current preacher/congregation transfer; no exported connection to “because you sold me here.” | Quarantined solely for boundary withholding: raw `local_sufficient` .62. |

The first directive is complete as an invitation/challenge; the second is complete as a forgiving reassurance/directive. Identity is established within the supplied envelopes. Broader source excerpts were checked for reporting continuity and contrary qualifications; they do not add an absent act or rescue missing supplied identity. R053’s repeated sentence and later circumstance are context, not a new semantic target. The proposed exhibits retain exact spans, full reviewed excerpts, source stance and scope exclusions for inspection.

## Smallest principled change

Introduce **`g3-atomic-admission-a1`**, a distinct local-act admission route with item schema `reviewed-atomic-local-evidence-a1` and witness schema `receipt-bound-atomic-act-sufficiency-a1`. Leave G2 and frozen V4 admission unchanged. Do not mutate Measurement or substitute a new answer for `boundary`.

For this route, require affirmative, claim-specific sufficiency from a separately accepted, receipt-bound source review. The witness must enumerate every actually observed act to export, exact utterance and preserved conditions, source/recipient/stance evidence inside the supplied envelope, completeness reasoning, explicit exclusions and the applicable policy/item versions. Bind it to the existing packet, measurement, phase/question/model/receipt identities, source hash and envelope. Generic `target_complete=True` is necessary but is not sufficient authority for this new scope. The V4 review acceptance alone cannot authorize A1.

The boundary field may be gated `local_sufficient` or `unclear`; in the latter case it supplies **no affirmative evidence**. The new witness supplies the narrower completeness finding. A definite gated `continuation_required`, an unknown category or an explicit incomplete target/context still blocks this route. That conservative exclusion is not a reinterpretation of the question; cases outside it remain deferred. Keep broader circumstance-dependent exports outside A1.

Everything else remains a required admission condition:

- All exported acts must already be measured `observed` at .80 and independently supported in the exact utterance. Review cannot manufacture a withheld act. Any unsupported positive blocks the entire row; no cherry-picking its safe fields.
- Measured voice, recipient and adoption must each remain definite at .80, agree with source review and satisfy the existing current/reported compatibility rules. Review cannot fill a measured unknown. Historical/reported/hypothetical acts stay in their reported namespace; no automatic pastor credit or current-listener transfer.
- Preserve phase isolation, exact coordinates, immutable raw answers, source continuity, context/target completeness, narration and God exclusions, null-circumstance consistency and vetoes on unsupported positive relevance/binding. Unknown relation decisions stay unknown and never become an exported relation.
- Each item explicitly declares `atomic_act_only`; exports only supported acts, exact utterance/conditions and provenanced scope. `circumstance_claim`, pastor projection and quality score stay null. Any circumstance pointer in raw roles is diagnostic, not evidence of connection.
- Recheck the accepted policy and claim witness on actual export, deserialization and local consumption. Old readers reject the A1 item version; there is no silent V4 upgrade, raw/quarantine fallback or legacy adapter.

This replaces a broad **admission prerequisite for a new claim scope**; it does not lower .80, rewrite a raw decision or make source review a general semantic override. It also does not establish an automatic sufficiency/provenance resolver. Codex can prepare the bounded review, but source-controlled review remains a safety oracle rather than a demonstrated scalable collection architecture.

## Design-only assessment against V4

The JSON records every original admission and remaining blocker. The following are proposed consequences, **not results of an implemented A1 gate**.

| Cases | Prospective assessment with the proposed accepted claim witnesses |
|---|---|
| R018 / R053 | Eligible as current-preacher / reported-local respectively; no circumstance claim. These are the only proposed additional items. |
| R078 | Still blocked: narration veto, no addressed utterance, unsupported reassurance and incompatible provenance. |
| R073 | Still blocked: Father Gabriel’s reported speech measured as preacher; recipient and adoption withheld. |
| R111 | Still blocked: reported/hypothetical Bruce offer measured as preacher/current listeners; adoption withheld; exact reported/hypothetical recipient alternative also unresolved in source review. |
| R114 | Still blocked: Knapp’s request to Crosby measured as current-listener address; voice/adoption withheld. |
| R076 | Still blocked: God recipient, incomplete prayer fragment, no observed human act, withheld voice. |
| R092 | Still blocked: clipped reported challenge and withheld recipient. Context cannot finish the exact target. |
| R077 fragment | Still blocked: incomplete conditional, no observed act, unresolved voice/recipient and unsupported definite relevance. Context cannot donate the omitted promise. |
| R077 complete promise | Still blocked: measured recipient unclear. The .54 current-listener argmax is not a decision. Review cannot replace it with reported person. Conditions remain intact. |
| R038 / R103 / R057 | Still blocked: no measured act and/or withheld recipient/adoption. Supported source material does not replace missing measurements. |
| All 11 G2 cases | Unchanged: R003 and the explicit R004 gloss admitted; nine blocked. R021’s false explanation and R080’s nonbiblical anchor still blocked. |

Thus simply deleting the boundary reason is not the proposed proof. The two additional possibilities require new explicit claim-scoped authority, and every other blocker remains. Seven confirmed raw errors stay errors. No current quarantine has been removed.

## Prospective anti-vacuity decision

**Yes: this can provide a valid, narrowly scoped anti-vacuity test without additional provider requests.** It would test the admission architecture on already measured evidence, not Jev’s unseen-case accuracy. The policy was designed after these observations; passing this development panel cannot establish general safety or unbiased error rates.

The smallest next implementation is one distinct G3 admission policy and typed claim-witness/item version, sharing existing identity, phase and provenance checks. Add focused deterministic tests of missing/unknown/wrong-claim sufficiency, unsupported additional act, wrong/unknown voice or recipient/adoption, clipped qualifiers, narration/God, forged/stale policy/review/receipt, schema mixing and export/deserialize/consumer bypass. Include a definite `continuation_required` fixture to prove this new route fails closed. Do not change frozen V4 artifacts or make paid requests.

After implementation is separately authorized, prepare a fingerprint-bound **provider-free policy-replay packet** with immutable expectations and separately proposed claim witnesses. Reuse all 24 cases / 37 sealed receipts: this is a tiny local regression panel, not a full-source semantic rerun. Exercise the real typed export, deserialization and consumer paths. Require both R018-current and R053-reported positives with exactly the source-supported acts, all incompatible/unknown controls blocked, and exactly the existing two G2 outputs. Independently source-review each emitted field and any unexpected admission; preserve each withheld/unsafe raw field.

Any unsupported admitted item means FAIL. Missing either supported G3 family means HOLD. If both pass and zero unsupported/unresolved items are admitted, recommend **A1 reviewed atomic-local containment PASS on this bounded panel only** for Brian’s decision. Do not relabel V4. Automatic provenance, review throughput/deferrals, discovery, opportunity denominators, recurrence and corpus economics remain unestablished. Discovery-readiness planning would then be a separate decision; collection and pastor projection remain held.

Current read-only packet check (no A1 gate execution or authority creation):

```sh
pte analysis g3-atomic-admission-review
```

This verifies pinned V4 evidence, the accepted FAIL/HOLD decision, original real V4 replay, and consistency of this authored design assessment. A successful check is not semantic or containment acceptance. No new semantic run is recommended.
