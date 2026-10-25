# Bounded automatic fingerprint preparation — Ollama revision

`pte analysis learning-demo` is the user-approved Ollama revision of the V3 adapter over `pastor_evidence`,
`pastor_fingerprint`, `pastor_similarity` and `evidence_requests`. It preserves the
existing profile 318/V8, profile 130/P1 and exploratory Scripture benchmark commands.
The new fingerprint panel seam does not rank profiles or alter Scripture geometry.

Prepare the authorized six-recording panel without providers or database writes:

```sh
pte analysis learning-demo prepare --base-dir /Users/briancummings/Documents/PastorSearchData --proposal /Users/briancummings/Documents/PastorSearchData/evaluation/learning-work-package-v1/proposal-v3/proposal-v3.json --json
```

Add `--check-only` to reproduce preparation without writing artifacts. Preparation
validates proposal/companion/source hashes, current membership and source gates,
actual saved neighboring blocks, score-independent controls, compatible constituent
cache identities, and the 24 serialized source-reading requests. It freezes schemas,
prompts, model pins, topic measurements, source references, code identity, token
accounting, downstream batch construction rules and all phase reservations under
`<base>/evaluation/learning-demo-v3-ollama/<input-fingerprint>/input.json`.
The original V3 packet and its prior OpenAI preparation remain immutable historical
inputs. The new manifest records the explicit provider/budget/context delta.

`preparation.md` beside that file contains exact preflight, M5 and reporting commands.
`run --check-only` checks frozen implementation, membership/source/run lineage,
request identity, installed model hashes and conservative input bounds, without
inference or attempt files. Preparation inspects model files; it does not load,
pull or run a model.
Paid `run` requires the separate explicit `--experimental --approve-input <exact
fingerprint> --max-usd 0.10 --confirm-verifier-price` decision and `TYPESAFE_API_KEY`.
Generation uses only local Ollama `gemma3:4b`; no OpenAI account/key is required.
At most 33 local generation attempts and 33 paid Jev attempts are allowed.
The verifier reservation is $0.090832896 at the inherited $0.042/million input-token
rate, with a $0.10 total paid ceiling ($0.07 source / $0.03 downstream). Local
hardware/electricity costs are outside this API accounting.
Do not execute that command as part of M1–M4. Current account access is unverified by
provider-free preparation. Price changes require a revised decision, never a larger
ceiling or replacement model.

All attempts reserve worst-case phase cost before sending; receipts are immutable,
cache reuse is exact, retries/fallbacks are zero, and uncertain spend stops the entire
run. All dynamically generated batches undergo request and per-question fit checks.
Input/output overflow stops explicitly; it never strips qualifications or adds batches.
Ollama uses UTF-8 serialized-byte upper bounds plus 4,096 framing tokens rather
than incorrectly applying an OpenAI tokenizer to Gemma. Each request explicitly
allocates enough context for its input upper bound and output cap, rounded up to
1,024 tokens, at most 131,072. The per-request input upper bound must not exceed
122,880; output caps remain 8,192 for reading and 4,096 downstream. These are
conservative bounds, not exact Gemma token counts. Local memory/latency at these
context sizes and semantic quality remain untested until separately authorized
execution. No source text or qualifications are truncated. TypeSafe uses a conservative
UTF-8 byte upper bound plus framing at the default 32k-question/64k-request limits,
reserving 65,536 charged input tokens. No long-context opt-in is used.

The installed Ollama manifest, weight/config/template/parameter blobs, local
loopback endpoint, native JSON-schema format and deterministic decoding options
are frozen. Changed tags/blobs, remote/cloud endpoints, missing local models,
incomplete responses and output overflow stop without retries, model downloads
or provider fallback. See the official [chat API](https://docs.ollama.com/api/chat)
and [structured-output contract](https://docs.ollama.com/capabilities/structured-outputs).

Automatic observations use the existing literal compiler under a machine-origin
contract. Literal checks and verifier probabilities do not establish human review or
production admission. Raw observations, failed bindings, unresolved assignments,
first narratives and removed clauses remain available. Fingerprints retain qualified
meanings, adopted affirmation/denial/unresolved sets, original observations, source
coordinates, independent uncertainty categories and separate topic estimands.
Parent metrics pool unique IDs within one operator; there is no overall score.
Relation absence requires an explicitly assessed matched-endpoint opportunity.

The same deterministic builder serves candidate and reference inputs. Production
requires a separate evidence policy; experimental records cannot pass it. The
benchmark adapter supplies SampleSpec/EvidenceView inputs to the same kernel rather
than accepting authored reference theology.

Interpretations require at least two supported, aligned premises, exact scope,
alternatives and defeaters, plus semantic checks. Substantive narrative clauses use
structured entry IDs and their complete dependency closure. Failed clauses are
removed once; generation never repeats until it passes. All six recording-omission
views rebuild evidence sets, measurements, masks, comparisons and supported
hypotheses. Old pair prose is withheld after numerical inputs change.

`report` shows preparation state or persisted run accounting and source-stratum
coverage. Its optional `--audit` is an offline M6 consumer, excluded from every runtime
model request. Blinded reference tags drive family/complexity retention, false
rejection, coverage, descriptive Wilson intervals and selective-loss diagnostics.
An audit packet is prepared by Codex after the separately authorized run; Brian is
not assigned JSON authoring or source annotation. Runtime repair/approval remains
zero. Semantic PASS needs all acceptance components and adequate independent
reference denominators; component FAIL and source/reference INCONCLUSIVE remain
distinct. Stubbed workflow success does not establish theological accuracy.

Focused provider-free development checks:

```sh
PYTHONPATH=tests python -m unittest test_pastor_evidence test_pastor_fingerprint test_evidence_requests test_learning_demo test_learning_demo_cli test_theological_binding test_profile_evidence_supply test_profile_explanatory_descriptions test_profile_presentation test_profile_portability test_benchmark test_cli_contract
```

No corpus classification, dataset comparison, reclassification, cohort collection,
closed-experiment execution, production materialization or admission change belongs
to this preparation slice.

HTTP status and response text are saved immutably under `execution/wire-responses`
before decoding either provider's response. Incomplete Ollama responses are rejected
before reading optional usage fields. Missing usage on an otherwise completed response
also halts; usage is never fabricated. Malformed JSON and HTTP errors produce halted
receipts, and `report` retains unknown-usage accounting. Network failures without a
response retain the existing uncertain-attempt stop.

The first authorized Ollama execution (`52aad7b4…`) stopped after one local attempt
with missing `prompt_eval_count`. That version lost the response before writing a
receipt. Its attempt and stop artifacts must remain immutable; this fix cannot recover
the output or make that run resumable. Changed implementation hashes also invalidate
the old preparation for execution. A technical restart requires a separately approved
preparation and explicit accounting for the prior local attempt; do not delete the
attempt, refreeze and rerun to bypass the no-retry decision.

Brian subsequently approved exactly one technical restart. `prepare --restart-from
<original-input.json>` supports only the preserved `52aad7b4…` failure with one local
attempt and no paid attempts. It freezes hashes of the original input and execution
records and requires unchanged sources, prompts, schemas, requests and model. The
new manifest permits 67 cumulative attempts (34 local, 33 paid), including the original
failed local attempt. The executor still permits only 66 attempts in the new run,
with the original phase limits and $0.10 paid ceiling. Reports expose prior and
cumulative accounting. Execution immutably claims the exception for one new input;
a second input cannot reuse it. This exception provides no automatic retry or model
fallback. Brian runs the prepared command; preparation performs no inference.

## Model-independent source contract revision

The approved follow-up keeps Gemma 3 4B, the same 24 windows and 66-slot recipe,
with no model adapter or additional extraction calls. Reading enums are enforced in
JSON Schema using the existing binding vocabulary. Explanatory fields have 512-character
limits; proposition/scope/qualification and downstream substantive prose have
1024-character limits. The validator rejects overflow; it never shortens returned
content. Source quotations have no prose-length cap. Complete qualifications must
remain visible; a source reader reports saturation rather than silently dropping them.

The model returns each span as `{source_field: "target_text", text: "verbatim passage"}`.
The producer locates the exact passage only if it occurs once, including Unicode,
whitespace and punctuation. Repeated or absent text remains an explicit literal-binding
failure; there is no fuzzy matching, first-match selection or manually supplied offset.
The same unchanged theological binding compiler then checks the canonical coordinates,
node references, adoption evidence and conditions. Original model output remains in
receipts and raw readings; the observation's producer identifies the locator version.
Semantic verification and production admission safeguards are unchanged. Prompt and
schema changes invalidate prior requests; historical responses are never reinterpreted.


`prepare --contract-round-from <393cbb32…/input.json>` freezes the separately approved
contract revision round. This is distinct from the earlier unchanged-request technical
restart. It pins both historical inputs and execution records, including the preserved
incomplete HTTP body, and checks unchanged sources, model, windows and acceptance
criteria. Maximum current-run attempts remain 66 (33 local, 33 paid), with 68 cumulative
attempts including the two failed local calls (35 local, 33 paid). The $0.10 total paid
ceiling and phase reservations remain unchanged. An immutable marker on the prior
execution binds this approval to one replacement input when Brian executes its command.
A later model adapter or model change requires the results and a separate decision.
