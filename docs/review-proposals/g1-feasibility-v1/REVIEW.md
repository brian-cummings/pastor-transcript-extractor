# G1 bounded implementation and feasibility handoff V1

Status: **authorized bounded implementation; prepared, empirically untested** — 2026-10-14. Brian explicitly authorized this step after accepting/closing the observed-profile consumer and its two conservative oracle deviations. This supersedes the earlier G1 implementation hold **only for this fixed pilot**. Full G1 expansion/collection and all downstream holds remain.

The purpose is local **measurement feasibility**, not G1 completeness or a theology extraction program. The original [G1 contract](../g1-binding-v1/CONTRACT.md) and its 20 authored cases remain unchanged as the bounded semantic basis. Scope stays at assurance knowability/loss/retention and the synthetic city-ramp requirement; no additional doctrine, public policy taxonomy or pastor position is introduced.

## Brian's exact next command

With the venv already active, from the repository:

```sh
pte analysis g1-feasibility-review
```

This is the **provider run reserved for Brian**. Codex has not executed it. The fixed inputs and expectations are complete; no selection, JSON authoring or annotation is assigned to Brian.

Provider-free integrity check:

```sh
pte analysis g1-feasibility-review --check-only
```

`--prepare-only` regenerates the same fixed artifacts without inference. Supplying both flags is rejected. No generic input/cohort option or expansion switch is exposed.

## Prepared artifacts and execution bounds

- [input-v1.json](input-v1.json): fingerprinted sources, exact target/context, lexical candidates, authored expected claims and prepared checks.
- [input-v1.md](input-v1.md): complete readable cases and expectations.
- [questions-v1.json](questions-v1.json): exact per-case independent questions and finite source-span options.
- [sermon_g1_feasibility_review.py](../../../src/pastor_transcript_extractor/sermon_g1_feasibility_review.py): isolated implementation; no database or production adapter.

| Bound | Default |
| --- | --- |
| Cases | 28: 20 original authored cases, five authored boundary additions, three fixed archived natural negative controls |
| Source candidates | 37 sentence/window candidates, built independently of expected labels |
| Model | `jev-1.13.0`, pinned; resolved-model mismatch rejects response/cache credit |
| Provider ceiling | **37 attempted requests total**, cumulatively enforced across resumptions |
| Request shape | One candidate per request, independent Choice questions in the same request |
| SDK retries / timeout | 0 retries; 45 seconds per request |
| Experimental decision policy | Selected-answer probability ≥0.80; otherwise withhold as `unclear` |
| Production effect | None; all outputs are isolated review artifacts |

Questions preserve subject/object binding, relation, voiced polarity, expression, voice, adoption, literal uncertainty evidence, scope evidence, claim-specific qualification and local sufficiency independently. Source-selected voice/adoption framing is retained as binding evidence. Raw choices/probabilities/confidence and requested/resolved model provenance remain available. The .80 policy is an explicit experimental withholding default, not calibrated production reliability or a confidence interval.

Output locations after Brian's run:

```text
evaluation/g1-binding/feasibility-v1.results.json
evaluation/g1-binding/feasibility-v1.results.md
evaluation/g1-binding/cache-v1/request-ledger.json
evaluation/g1-binding/cache-v1/<identity-hash>.json
```

The ledger counts attempts **before** calling the provider and records returned model, request ID and token usage before response validation. Failed/mismatched responses consume budget; they do not create valid cache credit. Known cumulative token totals and unknown-usage counts are reported separately. Cache identities bind exact state, questions, model, version and packet fingerprint. Successful cache replay makes no new provider calls and does not count usage twice. Corrupt caches/ledgers stop rather than silently spending to repair them.

On failure, execution-failure Markdown/JSON identifies incomplete execution, with successful caches and ledger retained. **Do not delete/reset the ledger or force a rerun to bypass the request ceiling.** If failed attempts prevent completion within 37, Codex interprets the failure and prepares a concrete recovery decision; Brian does not design it. No automatic retry/tuning cycle is authorized.

## Boundary controls and declared limitations

The original 20 cases distinguish present knowability from permanence, affirmation/denial/open issue, explicit uncertainty from a bare question, own/adopted from reported/rejected voice, qualified retention/support, wrong public objects, unresolved referents and context-only claims. The five additions make the latest requested boundaries explicit:

| Case | Prepared expectation |
| --- | --- |
| B01 | “Some teachers say … but …” preserves the report; no fully specified adopted alternative is invented. |
| B02 | Salvation topic treatment alone yields no proof-vocabulary proposition. |
| B03 | Discussion of ramps alone yields no support, opposition or prescription. |
| B04 | Opposing local claims with different explicit circumstances keep their scope; contradiction/coherence judgment remains absent. |
| B05 | A ramp qualification does not attach to the adjacent salvation proposition. |

Three fixed archived source windows control forgiveness/reporting, a Scripture-transition statement and salvation-themed material without one of the proof predicates. Their original video/block/time locators and archived-file hashes are retained. **They are natural negatives in this bounded vocabulary, not natural positive validation.** No natural-positive accuracy, automatic candidate recall, full episode boundaries or corpus negatives can be claimed from this pilot. Natural context windows are at most 350 characters on each side; truncated context is not complete episode evidence.

Candidate building does source-coordinate splitting and lexical phrase pools only. Expected claims, check labels, pastor names, titles, previous probabilities and semantic outcomes are excluded from provider state. Code copies selected literal spans; it does not generate a proposition or a pastor belief. Additional valid or erroneous positive candidates are all retained for Codex's source review. An empty qualification list means none is bound in this candidate, not unconditional teaching. `unclear` about a model judgment never becomes expressed pastoral uncertainty.

## Interpretation and stopping decision after Brian runs

Codex reads the raw results and every positive/partial record in its exact source scope, classifies omissions, unsupported semantic binding, frame/adoption transfer and conservative withholding, then recommends **PASS / PARTIAL PASS / FAIL** for Brian. No numeric match percentage automatically grants PASS.

- **PASS for bounded feasibility** if the prepared distinctions preserve local proposition identity, object, voiced stance, adoption, conditions/scope and explicit uncertainty without the critical inventions below. Isolated conservative withholdings can be accepted only as named limitations. Natural positive reliability remains unestablished regardless of this decision.
- **PARTIAL PASS** for coherent partial records with an important unresolved binding or localized critical error requiring a separately reviewed disposition. Correct argmax below threshold remains withholding, not a match. A disputed expectation is reviewed explicitly; do not silently rewrite it.
- **FAIL** for systematic object/stance transfer, manufacturing an adopted opposite, source-free uncertainty, context-only assertion transfer or topic-to-proposition invention.

Any confident critical error must be identified and prevents an unqualified PASS until explicitly adjudicated. False support from denied opposition and rejected/report-only claims is checked across **all** candidates, not only the originally expected one. Source-offset validity is not semantic accuracy. Preserve candidate omissions, extra positive interpretations and conflicting scopes without a G4 verdict.

**Make the feasibility decision and stop.** There is no automatic revision, doctrinal expansion, downstream consumer activation or collection step. G2/G3 construct iteration remains closed; the accepted observed consumer remains closed. G1 full collection/expansion, discovery recall, production calibration, opportunity denominators, request economics studies, pastor projection/comparison, clustering, G4, recurrence/rates and quality scoring remain separate held work.

## Development verification and integration basis

Nine focused mock tests pass: fixed inputs/state isolation, artifact drift, rejected-claim polarity, model versus expressed uncertainty, qualification/scope preservation, request/cache replay, resolved-model rejection, cumulative budget and native CLI modes. These are implementation checks, **not measured G1 semantic results**. No provider requests or dataset runs were performed during development.

The integration was checked against the live [TypeSafe Python usage guide](https://docs.typesafe.ai/sdk/python/usage), [Choice reference](https://docs.typesafe.ai/primitives/choice), [pre-parsed source selection cookbook](https://docs.typesafe.ai/cookbooks/pre_parsed_value_extraction_cookbook) and [retry reference](https://docs.typesafe.ai/sdk/python/api/retries), plus the installed SDK signatures. Some Markdown endpoints failed; the corresponding official pages were available. Independent questions share state but not answers; code owns source candidates, typed composition, abstention, caching and budget enforcement.
