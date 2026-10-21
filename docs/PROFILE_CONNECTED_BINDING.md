# Connected passage binding: bounded development workflow

> **Roadmap correction, 2026-10-20:** preserved experimental results. Their extractor/model follow-up recommendations are superseded by the [reuse-first implementation sequence](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md#active-work-sequence). No new variant, prompt/model change or provider run follows from this report. Use existing category-leaf evidence and put a demonstrated semantic gap at its responsible upstream producer.

**2026-10-20: Brian executed the bounded run; Codex completed cache-only diagnostics and source inspection. Decision: stop this full-contract configuration; no rerun or broader validation recommended.** Three `gemma3:4b` requests and seven metadata reads produced 14 raw propositions and 29 raw frames, but all three passages were rejected before proposition validation. Zero usable bindings remain. Usage: 3,409 input and 7,407 output tokens. No additional generation or metadata call occurred during review.

The original CLI count of zero referred to records reaching proposition compilation, not model output. All 14 raw propositions and 29 frames are now visible in the rejection diagnostics. The first missing-evidence error masked independent failures: all 29 frames lack attribution evidence; 30 literal references have out-of-range occurrence indices and seven texts are absent from their declared source; sixteen parent/child pairs cannot fit at any literal occurrences; all 14 propositions lack evidence for their affirmed polarity and assertion form. The ten P2 propositions also pair adopted with explicit_rejection and leave unknowns blank. Counts overlap and are not accuracy measures.

Source inspection also finds material meaning changes: Paul’s confession becomes a claim that humanity is inherently sinful, and Christ dying while someone was a sinner becomes coverage before sin is acknowledged. Completion, saving desire and the preacher’s middle-road critique are omitted outright. The missing evidence is not an isolated compiler inconvenience. It must not be supplied by changing indices, normalizing text, swapping parent IDs or relaxing evidence requirements.

The completed packet is at `evaluation/connected-proposition-binding-dev-v1/runs/4d338bc94526034602337fc395161f98744b1b85aefa8349391a053629d459f2/` under the app base. It contains `index.html`, `review-v1.md/json`, `semantic-review-v1.json`, `diagnostics-v1.html/md/json` and verification receipts. The ten reviewed readings each have twelve omission dispositions; all 14 raw propositions have additional source-inspected findings. Original model responses, digest pin, generation schema, compiler, runner, generated records and initial invocation receipt are unchanged. The report fingerprint is `d6c7aed4d2c1e9903a6c2a89effa6b5066feca922591ef96b51f929764fb4683`.

This workflow is a separate development increment. The TypeSafe V1/V2 results remain unchanged, including V2's negative decision. It is not an Ollama superiority claim, a provider ranking or production activation. The readable pastor profile and original ten reviewed readings/assurance interpretations are unchanged.

## Review the completed run

```bash
pte analysis profile-connected-binding --json
pte analysis profile-connected-binding --diagnostics --json
pte analysis profile-connected-binding --check-only --json
```

These commands use caches only. `--diagnostics` writes the exhaustive failure packet; `--check-only` writes nothing. **No further model execution is needed or recommended for this review.** The original `--run` entry point remains available for reproducibility, but do not start a new experiment on this result.

The completed run used the prepared defaults: the same three supplied passages, the existing configured `gemma3:4b` model at `http://127.0.0.1:11434`, one generation per passage, temperature zero, 16,384 context tokens, at most 8,192 output tokens per passage and 180 seconds per request. These context/output/timeout bounds belong only to this workflow; global configuration and other measurements are unchanged. The configured model must already be available. The command does not start Ollama, pull a model, run a health-test generation, retry, repair an answer or fall back to a remote model/provider.

A read-only preflight is also available:

```bash
pte analysis profile-connected-binding --prepare --json
```

Preparation loads exact-current source/reference identity and checks request bounds without contacting Ollama, constructing a provider or writing artifacts. It is not a model availability or quality test. The current request sizes are approximately 15–17 KB including the schema, with the full supplied target and existing context. Request bytes are not a tokenizer-based proof of context fit. Length-limited/incomplete outputs are rejected and retained; no partial JSON is admitted or automatically continued.

After execution, review and verification require no model calls:

```bash
pte analysis profile-connected-binding --json
pte analysis profile-connected-binding --check-only --json
```

The first command renders HTML, Markdown and JSON. The second reconstructs records from the saved raw response and verifies any completed semantic comparison, without providers or file writes. Initial execution statistics remain preserved when a command resumes from caches.

## What changed

`connected_proposition_binding.py` defines a strict schema for connected speech frames and propositions. Generation reads a whole passage directly; no lexical candidate menu, one-proposition completeness gate, named-speaker option list or model-probability cutoff controls discovery. A coherent compound can remain one statement. The model supplies literal quotes with zero-based occurrence indices; code locates them exactly and supplies source coordinates. It never fixes whitespace, paraphrases a quote or guesses a duplicate occurrence.

Frames retain parent/child containment, voiced speaker and actual/projected occurrence. An actual outer preacher question remains distinct from its embedded projected declaration. Each proposition points to its frame; an address act points independently to the frame performing that act, so the outer invitation can link to inner offered words. Projected words require an outer frame. A current-listener act requires an actual preacher frame.

The existing `theological_binding.bind` compiler remains the semantic boundary. Conditions/exceptions, nonconditional qualification nodes, G2 development endpoints and G3 address links retain their current meanings. Own assertion still requires actual preacher speech; adopted reported content still requires explicit endorsement or discourse-use evidence beyond the quoted words. A quotation alone does not establish adoption. No assurance predicate normalization is added, and no generated record is admitted or projected into the profile.

Code checks exact literals, field/schema shape, frame containment, parent cycles, node references, adoption consistency and evidence requirements. It does not establish whether an interpretation is correct, whether attribution evidence is semantically sufficient, or whether a paraphrase is faithful. Such failures remain matters for the source-inspected comparison. Invalid records retain their original proposed JSON and rejection reason; malformed whole responses/frames retain their raw cache and a passage-level rejection. Empty lists remain “none bound,” not proof of absence; unknowns are visible in the readable report.

## Backend, runtime and artifact identity

`connected_binding_development.py` reuses the application's `LlmConfig`, Ollama model-digest lookup and HTTP API conventions. Its small generation adapter preserves the complete raw response envelope, including token counts and completion reason; the existing generic client only returns parsed content. Structured output uses a JSON schema in `/api/chat`, as described in [Ollama's structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs) and [chat API](https://docs.ollama.com/api/chat).

Only loopback endpoints and an enabled local model configuration are accepted. At execution, a metadata-only lookup pins the installed model digest. Digest checks before/after each uncached generation detect a tag changing during the run. A fresh three-passage execution makes **at most three generation requests**, plus up to seven metadata reads. Compatible cached responses avoid both generation and metadata probes. No model files are modified.

The fixed source scope is videos **4589/block 47, 3973/block 75 and 281/block 123**, with their existing leading/trailing context. Reference answers, expected reading count, titles, historical TypeSafe decisions and G1 interpretations never enter the model input. The model receives only the extraction instructions, schema and three named text fields for its current passage.

Generated requests, raw responses, digest pin, durable request ledger, immutable generated records, execution receipts and review HTML/Markdown/JSON live under the configured app base at:

```text
evaluation/connected-proposition-binding-dev-v1/
  cache/<request-fingerprint>.json
  runs/<panel-fingerprint>/
    backend-v1.json
    request-ledger-v1.json
    generated-v1.json
    invocation-v1.json
    review-v1.md
    review-v1.json
    index.html
```

Cache identity includes the exact request body, local endpoint and pinned digest. The panel also pins current sources/context, reference identity for later comparison, prompt/schema and compiler/runner versions. An attempted transmission without a verified reusable response cannot silently retry. Raw responses are saved before JSON/semantic compilation and post-flight metadata validation. A changed digest or interrupted post-flight verification blocks reuse rather than accepting an unidentified result.

## Review ownership and remaining holds

Codex has reviewed every raw proposition and frame from this execution, including every rejected record against exact source and the same ten development references. The workflow reuses the twelve-field comparison validator and explicit extra-candidate dispositions. Differences can be acceptable alternatives, omissions, unsupported inferences, attribution/adoption errors, evidence-binding errors, other failures or correctly unresolved conclusions. No case selection, annotation or JSON authoring is assigned to Brian.

A successful transport or schema check is not a successful extraction. This run does not demonstrate useful connected meaning with defensible evidence. The completed report recommends no rerun or broader validation; it will not infer general accuracy, model superiority or ministry-wide stability from these development cases.

Broader collection, new measurements/admission, production activation, assurance changes, automatic acceptance/profile projection, benchmark comparison/ranking and the separate Ollama illustrative-quotation workflow remain held. This increment neither selects presentation quotations nor prepares that held runtime.

## Focused verification

Twenty new synthetic tests cover connected frame/use/address distinctions, complete compounds, exact/repeated literals, context exclusions, broken parents/endpoints, quotation-only adoption, schema/record rejections, raw-cache reconstruction/tampering, truncated/wrong-model/malformed outputs, digest drift, interruption guards, three-request limits, preserved initial receipts and provider-free/write-free CLI preparation/checks. They test code behavior, not model semantic quality. Four additional diagnostic tests cover independent simultaneous failures, absent text versus invalid index, impossible containment, mutation-free inspection and backend-free CLI diagnostics. The focused profile/binding suite contains 113 tests.

## Interpretation and next action

Keep using the source-reviewed profile and ten defensible readings. Stop this full-contract `gemma3:4b` binding experiment here. This is a case-specific failure of this configuration, not a finding that TypeSafe or Ollama is generally superior. If automatic binding is pursued later, first reduce the generative burden of graph IDs and occurrence counting and demonstrate a minimal exact-quote/attribution/evidence contract on synthetic controls. Such a proposal is not a remedy for this saved run and does not authorize another provider/model run. No annotation or repair work is assigned to Brian.

`connected_binding_diagnostics.py` is a separate cache-only observer. It does not modify the frozen compiler or schema. It reports all quote failures, missing evidence, incompatible use bases, impossible parentage and blank unknowns rather than stopping at the first passage error. Available literal occurrences are diagnostic context only: they never replace the model's invalid requested occurrence or create an accepted binding.
