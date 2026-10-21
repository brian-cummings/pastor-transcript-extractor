# Automatic generic proposition binding: bounded development workflow

> **Roadmap correction, 2026-10-20:** preserved experimental results. Their extractor/model follow-up recommendations are superseded by the [reuse-first implementation sequence](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md#active-work-sequence). No new variant, prompt/model change or provider run follows from this report. Use existing category-leaf evidence and put a demonstrated semantic gap at its responsible upstream producer.

**Current result, 2026-10-20: V2 executed by Brian and semantically compared by Codex. Decision: do not expand validation or run another menu/cutoff-tuning iteration.** The same three passages produced 35 structurally valid candidates in 39 provider requests (zero cache hits), using 503,108 input and 65,691 output tokens. A monetary cost was not returned. All subsequent comparison, verification and report formatting used caches with provider construction blocked; Brian's original invocation receipt remains unchanged.

Seven reviewed proposition contents are located, none are partial and three are missing; **zero readings preserve all twelve reviewed field groups**. Paul’s confession, the reported middle-road identity and the place-in-heaven declaration are newly located. The mercy account, saving-desire statement and lukewarm warning are now missing. This trades which content is recovered; it does not establish faithful binding or general improvement. All 26 unmapped generated candidates have source-inspected dispositions; extra source-backed theology is not automatically a false positive.

Seven generated candidates have structurally resolved voice/speaker pairs, but two repeated Jesus lines cite only an unattributed line as attribution evidence. All 35 adoption states remain undetermined. No qualification, development-link or address-act record survives. P3 outer invitations now withhold occurrence instead of emitting V1's projected occurrence error; the supported actual preacher frame is still absent. No generated observation is accepted or projected into the profile.

**Concrete failures:** relevance 1.00 does not save the complete saving-desire compound statement from a boundary score of .57, or the attributed warning from .78. The mercy prayer has no complete standalone lexical candidate; its broad paragraph has boundary .64. Conversely an incomplete scoundrel-if fragment passes the boundary gate. Paul and invited-listener identities are often recognized, but competing evidence windows withhold their voice bindings. Even the completion claim's resolved preacher frame leaves own assertion and adoption split. The explicit unknown disclosures are useful, but do not supply the omitted G2/G3 links.

**Recommendation:** retain the source-reviewed bindings as current usable evidence and stop further tuning of this selection-based binder. The next proposed architecture extracts a connected proposition, speech frame and evidence structure from each whole supplied passage, validates literal spans in code and uses narrow judgments afterward for verification. Any new backend or provider experiment needs a separate decision; no Ollama execution, model comparison or quotation work is authorized by this result. This is a diagnosis of this implementation on these cases, not proof that another model is better.

The V2 packet is under the configured base directory at `evaluation/automatic-generic-proposition-binding-dev-v2/runs/0e8c2a1ae48b2bcc4b3a9511bb2bfea055a794967f4c10292eaf5a87cb6c9eb8/`: `index.html`, `review-v1.md/json`, `semantic-review-v1.json`, immutable `generated-v1.json`, the original invocation and verification receipts. Report fingerprint: `63c63f7c007eeabbb558c147cbddae736c259ac16a95ea61ff245ae232eaa9af`. Generated fingerprint: `c817a55019514eedc221951f5be82f547677d7ef4c3de74364deb15eb2526ba0`. The report links to the original discovery, frame and interpretation requests and raw probabilities. To keep those relative receipt links available over HTTP, serve the V2 evaluation directory with the report at `runs/<fingerprint>/index.html`.

## Preserved V1 result

**2026-10-20: V1 executed and semantically compared; decision: do not expand validation yet.** Brian directly approved this small TypeSafe run as an exception to his normal preference to execute validation commands himself. The earlier automatic-approval block is resolved. The run used only the same three passages and ten development references; no reference answers entered generation.

The run produced **24 candidates**, all literal/structural checks passing, from **15 provider requests with zero initial cache hits**. Usage was **518,549 input tokens and 59,674 output tokens**. A monetary cost was not returned; none is invented. Final artifact reconstruction reused **15 local response caches with provider construction blocked**, making zero new model calls.

The source-inspected comparison finds **six readings with matching proposition content, one partial mercy account and three missing readings; zero readings faithfully preserve all reviewed field groups**. “Located” is content recovery, not full binding. The missing readings are Paul’s confession, the reported middle-road identity and the invited place-in-heaven declaration. All 16 extra generated candidates are also reviewed; valid extra theology is not called a false positive merely because it is outside the ten references.

Only one generated candidate fully resolves voice/speaker (Jesus’ warning). All 24 adoption states are undetermined; no qualification, development-link or address-act record survives. The actual outer forgiveness invitation is wrongly marked projected; the inner declaration is correctly projected. Five additional outer questions/directives have the same occurrence error. Conditions are not invented, question form is not turned into expressed theological uncertainty, and no permanent-security or actual-listener-status conclusion is manufactured. Those safe withholdings do not compensate for supported fields that were omitted.

**Smallest remedy:** keep these cases fixed; separate actual outer speech frames from projected inner propositions, split mixed caption paragraphs, distinguish proposition actor from voiced speaker, narrow overlapping evidence/speaker menus and bind attribution before dependent adoption/use judgments. Discovery should distinguish candidate completeness/redundancy from theological relevance. Do not lower the frozen `.80` development cutoff to improve the appearance of this result. No wider sample or independent validation is recommended on the current result.

The preserved V1 packet is under the configured base directory at `evaluation/automatic-generic-proposition-binding-dev-v1/runs/1037d3fc710038198075d085f1f636e56f3a323a9bf6593813622713f1bbdcfb/`: `index.html`, `review-v1.md/json`, `semantic-review-v1.json`, `generated-v1.json`, and the invocation/verification receipts. Report fingerprint: `3a4e8631911b6d3279c7bd5f828fe41ba3925a4b151a3c501fc92e5b89c50593`. The initial live-run artifact remains separately preserved; the final generated bindings are identical to it. Only presentation/semantic comparison changed after outputs were inspected.

## Runnable entry points

All commands below now address **V2**, stored separately under `evaluation/automatic-generic-proposition-binding-dev-v2/`. V1 artifacts are not overwritten or relabeled; open their saved HTML/Markdown/JSON directly at the path above. V1's original implementation is preserved in Git through commit `91d5f54`.

Read-only preflight, without provider construction or artifact writes:

```bash
pte analysis profile-binding-development --prepare --json
```

The execution/resumption command is preserved for reproducibility; **do not run it again for this review**:

```bash
pte analysis profile-binding-development --run --json
```

Render the completed V2 results and semantic comparison without provider calls:

```bash
pte analysis profile-binding-development --json
```

Verify source identity, request caches, reconstructed generated records and the comparison without providers or artifact writes:

```bash
pte analysis profile-binding-development --check-only --json
```

The latter commands reuse the completed V2 run without opening a provider. `--prepare` checks source/request preparation only; it is not an execution-status query. V1 caches cannot satisfy changed V2 requests. Generated results, raw response caches, request ledger, invocation receipt and HTML/Markdown/JSON review live only under the configured application base directory, never the repository. The command rejects repository-local artifact directories. An interrupted transmission without a reusable response requires inspection and cannot silently retry.

## Implementation and boundaries

`automatic_proposition_binding.py` builds literal source candidates from punctuation/quotes, with generic lexical windows for punctuation-poor captions. TypeSafe judges relevance and boundary separately, then resolves a speech frame before dependent interpretation; code copies the exact source wording into the existing generic structure. It does not receive the ten reference records, their expected count, G1 decisions, reviewed G2/G3 labels, titles or paraphrases. Whole source passages and existing context remain available for attribution and discourse use; context cannot supply a missing assertion.

`profile_binding_development.py` owns the fixed three-passage guard, discovery/binding requests, compatible raw-response caches, interrupted-request protection, literal/structural compilation, result verification and readable comparison. It reuses the existing TypeSafe SDK transport with zero SDK retries, without executing the closed G1 experiment or using its predicate menu. A request is durably logged before transmission. An attempted request without a cached response cannot be silently repeated. Compatible requests reuse exact model/state/question caches.

Only videos **4589/block 47, 3973/block 75 and 281/block 123** enter the run. V2 currently produces **43, 54 and 12 lexical candidates**, respectively; these are not accepted propositions or a discovery denominator. Relevance and complete-boundary decisions must both pass before binding. There is a ceiling of 40 included candidates per passage and two candidates per frame/interpretation request. The configured attempted-request ceiling is 123 (three discovery requests plus at most 60 frame and 60 dependent requests); actual requests depend on inclusion. This is a safety ceiling, not an estimated bill. Nothing silently truncates a larger result. No duplicate-suppression policy or lowered probability cutoff is introduced.

The fixed `.80` selected-option probability rule withholds uncertain development choices. It is an unvalidated development abstention policy, not a changed assurance threshold, calibrated accuracy claim or admission rule. Independent incompatible answers are withheld with diagnostics rather than repaired to reproduce the reference.

Generic voice, occurrence, preacher adoption, polarity, expression, scope, expressed uncertainty, conditions/exceptions, attached qualifications, G2 development links and G3 address acts remain separate. Act adoption/voice is judged independently of proposition adoption: owning an invitation need not assert a hearer’s saving state. Generated records are explicitly marked **automatic development candidates, not source-reviewed or accepted observations**. The original generic reviewed records and assurance interpretations are unchanged.

## Existing evidence reuse

The workflow reuses the exact current target/context windows, source/membership compatibility checks, generic compiler, G2 evidence-node/development meanings and G3 address/addressee distinctions. Inspection of the three current classification target blocks found context, scores and eligibility data, but no persisted G2/G3 bound-node records in those artifacts. This bounded check does not establish global absence of older or differently keyed evidence. The corresponding reviewed G2/G3 judgments in the ten reference records remain comparison material and are withheld from blind generation.

## Comparison and decision, owned by Codex

Codex inspected the actual output against the same source and ten development references, authored the complete semantic comparison under the application base and rerendered through `pte`. Brian is not assigned JSON authoring, case selection or open-ended annotation.

Every reading must show generated candidate links, the unchanged reference, agreement/material differences and correctly unresolved conclusions across twelve field groups. Dispositions are agreement, acceptable alternative, omission, unsupported inference, attribution/adoption error, evidence-binding error, other failure or correctly unresolved. Material discrepancies require exact source evidence. Every extra generated candidate must also receive an explicit disposition. Multiple generated candidates may support one reading, and merged wording can be an acceptable alternative only after semantic inspection.

The report counts those dispositions across these ten readings and individual fields; it does not call them general accuracy, precision, recall, production readiness or corpus validation. Structurally valid records are not automatically semantically faithful. Token usage and provider requests/cache hits are reported from receipts; a monetary cost is not invented when absent from the provider response.

The final decision must answer whether these development results justify a separate broader validation step. A negative answer must identify concrete failures and smallest remedies; a positive answer must propose the smallest independent validation. Both completed comparisons answer **no** for their implementations on these development cases. V2 supports changing the extraction approach before any further run, not repeating the V1 menu remedies. This is not a general claim about TypeSafe or automatic theological binding.

## Local verification

**V1 verification (preserved): 83 focused tests passed:** the 70 existing profile/pilot/plan tests plus 6 generator and 7 development-runner tests. New checks cover source-only state, literal quote/outer-frame candidates, withholding incompatible adoption/uncertainty, independent act adoption, cached replay without providers, ambiguous-interruption protection, resealed-result tampering, complete field-aware comparisons, evidence links, CLI isolation and write-free check-only. Mock provider responses are test fixtures, not development performance. Separately, the live run’s raw response caches reconstruct all 24 generated records exactly; the final cache-only materialization constructed no provider. Browser checks verify ten comparison sections, 24 generated sections, twelve field groups, closed technical disclosures, zero broken internal links and comparison → generated record → exact source → comparison navigation. The original ten reviewed records, all original G1 interpretations and the original V3 profile match their preserved artifacts.

No broader collection, additional sermons/pastors, production activation, automatic acceptance, frozen assurance changes, profile projection, benchmark comparison/scoring, ontology expansion or Ollama quotation execution is included.

### V2 verification and completed comparison

The focused suite now contains 89 tests. New regression controls cover multi-sentence quote boundaries, separate relevance/completeness decisions, attribution-only speaker candidates, disjoint request stages, dependent-frame linkage/tampering, explicit unresolved links and write-free/provider-free CLI preparation. Mock provider outputs check transport/composition behavior, not model quality. V2 preflight checks exact current source identity and both request-stage shapes/sizes. It does not execute a model or reuse V1's semantic verdict as a V2 verdict.

Codex inspected all 35 generated candidates against the source and unchanged ten readings, authored all 120 field dispositions and 26 extra-candidate reviews, and issued the negative expansion decision. Read-only reconstruction checks all 39 raw response caches and the exact generated records. Browser checks cover ten comparison sections, 35 generated cards, exact source/return links and raw probability receipt access. The original generic readings, G1 records, V1 report and V3 profile remain unchanged. No case selection or annotation is assigned to Brian. Neither provider superiority nor readiness for a wider sample has been established.
