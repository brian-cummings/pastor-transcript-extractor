# Selected windows → TypeSafe: interface and usage review

**Connected the selected-window handoff to a provider-free TypeSafe position plan and the existing measurement question factories. Actual TypeSafe/Ollama calls: zero.** No generative extractor is required by this plan. The remaining unvalidated capability is selecting exact G2 endpoints or a complete G3 utterance within an already selected context.

This work does not reclassify a sermon, choose another context or use oracle targets as nominations. It consumes the unchanged reconciled preparation `84ae2ce9dc0abd1bfd22a82a192df3a457fe9bae898a7dbab4eec163b8e5e7cc`. Its fixture-only membership scope remains unchanged; no source, classification, database or accepted measurement/admission decision was modified.

Prepared bridge fingerprint: `604a8d43c2a3d841fcd43a1916cfdc1b4bdf6be5ef75291e843e7f4f7153e98c`.

Generated interface/usage plan: [preparation-v1.json](/Users/briancummings/Documents/PastorSearchData/evaluation/typesafe-selected-window-bridge-v1/604a8d43c2a3d841fcd43a1916cfdc1b4bdf6be5ef75291e843e7f4f7153e98c/preparation-v1.json).

## What is already handled and what is missing

The 24 old diagnostic locators resolve to **17 contexts / 18 G2/G3 family bindings**. Context selection, exact canonical minute mapping and bounded source envelopes are done. They do not supply the exact endpoint arguments required by the frozen questions:

- G2 measures a specified `left` → `right` pair. It does not find arbitrary endpoints merely because a broad context is supplied.
- G3 measures a specified `candidate.utterance`. Sermon-boundary choices concern recording edges, not a complete P1 act. Their raw answers cannot be reinterpreted as utterance boundaries.

Existing saved outputs on these three sources are historical sermon-localization artifacts. No compatible exact atomic measurement is present in this handoff. A model/question/state/source-scope match is required for reuse; the same text, block ID, topic or a high sermon probability is insufficient. The check does not claim that every external cache was exhaustively searched.

## Minimal TypeSafe nomination interface

The new **prospective** question version is `minute-source-position-selection-v1`. It changes no closed G2/G3 measurement question or .80 gate.

Code exposes all canonical character boundaries as source IDs, with a neutral word-offset navigation map. TypeSafe selects IDs; code copies the source verbatim. There is no sentence/clause ranker, semantic pair lattice, generated text, reference-specific rescue, or quadratic enumeration of possible spans.

A Choice supports at most 255 options ([official API](https://docs.typesafe.ai/api)). The plan therefore uses at most 252 positions per page plus `none`, `unknown` and `needs_context`:

1. For each G2 pair, select the pages containing its four endpoint boundaries; for each G3 act, select the pages containing its start/end. Independent questions over the same context share one request.
2. Only families with complete page choices proceed to exact position choices within those pages. These use the **same selected source context**, not another retrieval window. Short contexts with at most 252 boundaries use one direct pass instead.
3. Copy the selected canonical spans, verify endpoint order, nonoverlap, source identity and center intersection, and retain only untrusted literal nominations. Invalid/inconsistent choices defer without repair, retry or expanded context.

The TypeSafe [line-ID example](https://docs.typesafe.ai/cookbooks/semantic_find) and [pre-parsed extraction example](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook) support selection among code-owned source choices. They do **not** validate this new boundary-selection task or prove sermon accuracy. Here, independent start/end selections still can disagree semantically; downstream review and measurement remain necessary.

To bound usage, this plan nominates only the earliest complete eligible object per family/context, with minimal complete endpoints. Other events remain **unenumerated**. This is an initial nomination-feasibility path, not full evidence collection and not a replacement for recall evaluation. The old focal 10/12 criterion and clipped-control geometry do not transfer.

## Avoiding unnecessary work

| Work | Offline result / proposed bound |
|---|---:|
| Selected contexts / family bindings | 17 / 18 |
| Contexts deferred by known measurement-scope incompatibility | 2 |
| Eligible shared contexts / family bindings | 15 / 16 |
| G2 / G3 family bindings | 6 / 10 |
| First-pass endpoint questions | 44, bundled into at most 15 requests |
| Second-pass endpoint questions / requests | At most 44 / 15 |
| **Selection requests** | **At most 30**, before exact reuse/withholding |
| Compatible first-pass cache leaves found | 0 of 44 checked |
| Downstream measurement requests currently prepared | **0** |
| Conditional later atomic measurement calls | At most 16, only after valid exact nominations and cache/scope checks |
| Unrequested G3 circumstance-binding calls avoided | Up to 10 |
| Extra presence/routing questions, repeated classifications, retries, generative calls | **0** |

Thirty is a proposed selection ceiling, not actual usage or execution authorization. Fully cached answers need no call. A sentinel for any required boundary stops that family before refinement; partial cache hits request only the missing questions in one shared-state call. Do not prepay fixed four-item enumeration, repeat source classification, fan out over span pairs, or add a separate presence question just to confirm the window already exists.

Exact per-question reuse keys include the full state, actual question/criteria, model, question version, phase and source/membership scope. Question IDs alone are not semantics. Corrupt or incompatible cache entries fail closed rather than triggering a replacement provider call. Cached selections remain untrusted and cannot create evidence authority.

For future execution, the serialized first-pass wire payloads total **519,848 UTF-8 bytes**; the largest is **42,302 bytes**. These are byte counts, not TypeSafe token/billing counts. Model access, exact token/context accounting, price, latency and active review ceilings are not locked in this offline plan. There is no provider client or execution command.

## Two structural deferrals before TypeSafe

**CE-22** and **CE-24** have selected context extending outside the frozen measurement materializer's reviewed main-source bounds. Their center might be inside, but the actual supplied envelope is incompatible with that materializer. Spending selection calls cannot change that fact.

They remain explicit structural deferrals. The plan does not silently clip the context, modify source bounds, infer a negative control answer or count them as containment successes. All 12 adequate diagnostic locators remain among the eligible contexts, but the selector proposes the first eligible object, which may differ from a focal reference. No focal recovery score is computed.

The bridge also rejects automatic attribution/context expansion by the legacy materializer: if its returned envelope differs from the selected context, no measurement request is produced. A different envelope needs an explicit prospective transport decision, not a hidden extra source lookup.

## Reusing measurement semantics without redundant calls

When a valid nomination is available, the bridge invokes the existing pure materializer and question factories. It preserves G2 question content and G3 act/source question content exactly; tests compare those dictionaries directly. It does not pass the whole window as an atomic utterance or inject position-selector labels as source voice.

For the **atomic-only, null-circumstance G3 route**, a circumstance relevance/binding phase is unrequested. Those fields remain **unmeasured**, rather than receiving fabricated `not_bound` values. This is a prospective measurement-use plan only: existing fixed V4/A1 packet validators, consumers and source-review authorities are not automatically compatible with absent relation fields or these new observations. No admission adapter is activated, and no new observation becomes usable evidence.

## Verification, history and next step

**90 focused tests passed.** They cover complete position coverage with the 255-option limit, direct/refined selection, early withholding, literal copying, invalid order/context-only targets, exact and partial cache reuse, stale model/state/question/phase/scope identities, corrupted cache rejection, unchanged measurement questions, unmeasured relation fields and blocked scope/expansion. All existing mapping, membership, historical CLI and probe-retirement tests pass. The old OpenAI probe remains superseded and blocked.

```bash
pte analysis structure-readiness --typesafe-windows --check-only --json
```

Without `--check-only`, this mode recreates only the fixed provider-free plan under the application base directory; it cannot infer. The existing `--check-handoff --reviewed-membership` command continues to verify the unchanged selected windows using the archived CLI byte pin at Git `e41aeb2`.

**Next recommendation:** review this small position-selection interface, then prepare a separately bounded **nomination-only TypeSafe execution packet** if accepted. Lock model/API/token/time/review/spend ceilings before execution and keep measurement/admission unrequested until actual nominees exist. No Ollama or new retriever is needed for that proposed test. Do not count this preparation as nomination feasibility, containment, discovery readiness or pastor-level evidence.

[review-v1.json](review-v1.json) binds the findings and usage plan. No paid request, SDK client, model load, source mutation, collection, automatic attestation, recurrence or projection/scoring occurred. Preliminary provider-free drafts remain outside source control; the active manifest points only to the final fingerprint above.
