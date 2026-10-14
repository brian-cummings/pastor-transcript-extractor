# G3 V2: one narrow relationship revision

**G3 V1: PARTIAL PASS — construct feasible; binding semantics require one revision.** Brian approved this bounded revision on 2026-10-14. The seven act questions and addressee, voice, adoption and boundary questions are frozen. Full G3, G1 implementation/expansion, G4, collection, projection/comparison and all empathy/quality scoring remain held. G2 tuning remains closed.

With the venv active, from the repository:

```sh
pte analysis g3-feasibility-review --revision v2
```

Provider-free integrity check:

```sh
pte analysis g3-feasibility-review --revision v2 --check-only
```

The default without `--revision v2` remains the frozen V1. No provider rerun has been executed during preparation. Inputs are complete: [fixed packet](input-v2.json), [readable cases](input-v2.md), [exact new questions](questions-v2.json), and [V1 mismatch audit](audit-v1.md). No case selection or annotation is assigned to Brian.

## What changes

The V1 binding question mixed semantic relationship with address to a person. Its criteria described an utterance's connection to a circumstance while its task used “address”; prayer's positive relevance was therefore a defensible answer to a field expected to exclude God as addressee. This is an **A: contract/expected-label issue**, not proof of a false listener act. Preserve the original raw results and expectations; do not relabel V1 as a match.

Replace that question with two independent judgments:

| Judgment | What it establishes | What it does not establish |
| --- | --- | --- |
| `circumstance_relevance` | The exact utterance concerns the specified circumstance. Topic discussion, prayer about people and reported speech can qualify. | Address to the person experiencing it, preacher adoption, or current-listener application. |
| `recipient_circumstance_binding` | The exact utterance addresses a human recipient **in that recipient's circumstance**, as evidenced in the target. A reported/historical recipient can qualify. | Current listener status or preacher adoption. |

Both preserve target-grounded versus context-resolved identity, negative, incomplete and unclear outcomes. Context resolves a person or “this loss”; it cannot add the absent address or its circumstance connection. Other target sentences cannot supply an act missing from the chosen utterance.

Current-listener pastoral-address evidence is a **composition**, not a third model question: observed act + demonstrated relevance + demonstrated human-recipient circumstance binding + `direct_current_listener` + `own_or_adopted` + sufficient local evidence. Each selected decision requires probability ≥0.80, inherited as an experimental threshold. Reports remain semantically representable even when the current-listener gate fails. Conditional subsets of the actual listeners count as listener address; imagined people without current application remain separate.

| Contrast | Relevance | Human-recipient binding | Addressee / adoption | Provisional current-listener act |
| --- | --- | --- | --- | --- |
| “God, comfort those who are grieving.” | Relevant in target | Not bound | God; independent stance | None |
| Reported “Stop crying” to mourners, explicitly rejected | Relevant in target | Bound to reported mourners | Reported person / rejected | None; the reported challenge remains visible |
| Retold Scripture reassurance to a man fearing unforgivable sin | Relevant in target | Bound to reported man | Reported person / report | None; reported reassurance remains visible |
| “If you need company through this loss…” with context identifying the loss | Relevant, identity resolved by context | Bound, identity resolved by context | Current listener / own | Invitation if the unchanged act/framing gates hold |
| Grief near an unrelated parking invitation | Not relevant | Not bound to grieving person | A real invitation to volunteers | No grief-sensitive listener act |

Relevance is intentionally allowed for topic-only discussion; it can never manufacture an address act. Prayer relevance alone is not an error. Recipient binding to God, wrong persons or context-only treatment is an error. Relevance and binding remain separate facts in raw artifacts rather than one opaque “pastoral” field.

## Frozen subset and reuse

12 exact existing candidates, with **no authored additions or changed endpoints/context**:

- G3-01 acknowledgment/perspective positive and G3-06 candidate 1 offered-care positive.
- G3-08 rejected report and G3-09 prayer about grieving people.
- G3-11 context-resolved invitation and G3-12 context-only leakage control.
- G3-14 candidate 1 challenge/warning relation previously withheld.
- Proximity and wrong-object controls.
- Natural 1200:32 candidate 0 busy-parent acknowledgment; 4430:57 candidate 0 reported reassurance; 590:64 candidate 1 prayer transition.

The warning-only candidate's V1 binding was already positive; its addressee/adoption abstention is retained rather than prompting it again. Other unchanged V1 cases remain baseline feasibility evidence, not fresh V2 confirmations.

Maximum **12 new provider requests / 24 new judgments**, pinned `jev-1.13.0`, 45-second timeout, no SDK retries. The **132 unchanged answers** (seven acts plus four framing fields on 12 candidates) are copied only after checking full original state, exact candidate endpoints, full per-question definitions, model identity, V1 cache identity/raw answers and input/result/source fingerprints. The original binding answers are shown for comparison but never reused as either new relationship. New questions see neither old answers nor expected labels, review reasons or pastor identities. No Scripture/style/leaf recollection. This reduces the rerun scope; corpus candidate/request optimization remains deferred.

Full V1 remains immutable. The revision has separate packet, question inventory, caches and results. Changes to original files, question meanings or provenance stop validation. Explicit `--prepare-only` regenerates a proposal, not a validation result; review any changed fingerprint before running it.

## Outputs and failure handling

- `evaluation/g3-address/feasibility-v2.results.json` and `.md`: every new relationship judgment plus unchanged act/framing answers, expected-label screens, provisional gates and baseline binding comparison. JSON preserves raw probabilities and per-question reuse provenance. The Markdown states that the retained act/framing answers are V1 evidence.
- `evaluation/g3-address/cache-v2/`: exact-state/new-question/model/source-bound answers. An unchanged rerun uses these caches.
- `feasibility-v2.execution-failure.json` and `.md`: incomplete execution, no semantic verdict; successful caches retained. Integrity/service/malformed-output failures are not semantic failures or successes.

Review all new positive relations and every current-listener proposal, not only expected-label matches. No accuracy aggregate or automatic PASS hides a critical false relationship. Preserve A/B/C classifications. An unchanged V1 uncertainty is not counted as a new failure, nor as resolved by this experiment.

## Acceptance and decision proposal

**Bounded PASS with documented limitations** if complete source-valid execution resolves the conceptual distinction and:

1. G3-09 is confidently relevant but not human-recipient-bound, with no listener credit. The natural prayer transition cannot inherit human-recipient binding from preceding material.
2. Reported/rejected cases establish real human-recipient relationships while remaining excluded from current-listener credit. Neither loses its reported act merely to make the gate pass.
3. G3-11 supports relevance and recipient binding with context-resolved identity, demonstrating reference resolution without importing an act. G3-12 remains unbound; no context-only address is manufactured.
4. Proximity/wrong-object controls produce no confirmed false relevance or recipient binding. Clean acknowledgment, care and natural busy-parent positives establish the two relationships. G3-14's challenge/warning binding is reviewed; isolated conservative recall can remain a named limitation rather than another tuning cycle.
5. Across the combined V1/V2 evidence there is no systematic false recipient/adoption transfer or act manufacture. Existing addressee/adoption abstentions and unlabelled V1 act concerns are disclosed. Clear semantic errors cannot be excused solely because another field happened to gate them out.

**Partial pass** if the representation is sound but a required prayer/report/context/proximity distinction remains unresolved or isolated candidate/judgment issues prevent these gates. Own a concrete A/B/C interpretation and recommend the next decision; do not automatically schedule another tuning cycle.

**Failure** if clear systematic recipient confusion persists—for example prayer-to-God becomes human-address binding, the wrong person's circumstance transfers, or context supplies missing treatment. Stop expansion and revisit the relationship representation. Any clear critical false edge prevents PASS; partial versus failure depends on systematicity and impact.

A pass would establish bounded G3 architecture only. The next implementation priority still requires a concrete joint G1/G2/G3 review and Brian's decision. No collection or pastor projection is authorized by this handoff.

## Local verification

Four focused revision tests and 18 CLI contract tests pass: original state/answer reuse, two-question-only requests with a mock provider, cache replay, model mismatch rejection, provenance failure, composition gates and native revision dispatch. Provider-free preparation/integrity checks pass. No provider evaluation was run on Brian's behalf.
