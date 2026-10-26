# Bounded DeepInfra source check

Brian authorized wiring one hosted DeepSeek V4 Pro check after the preserved local
thinking attempt exhausted 4,096 output tokens without a final answer. This slice
tests the feasibility of the same complete source window and two-claim qualified
observation contract on a larger hosted model. It does not resume a closed run,
change the fingerprint mathematics, perform pastor comparisons or grant admission.

Inspected reuse paths: the stopped thinking diagnostic's frozen system/source
messages, schema, source window, raw response and receipt; original source hashes
and six-recording lineage; existing literal locator and binding compiler; shared
request/cache/receipt executor and paid accounting. No reviewed answer or expected
pastoral interpretation enters a request. The missing information is whether the
hosted model returns complete, qualified, correctly attributed literal-bound claims.
The responsible boundary is source generation, not downstream profile prose.

## Frozen request

- Endpoint: `https://api.deepinfra.com/v1/openai/chat/completions`.
- Model: `deepseek-ai/DeepSeek-V4-Pro-0813`, the dated official release at the
  [documented price](https://deepinfra.com/deepseek-ai/DeepSeek-V4-Pro-0813).
- One window: `P318-R3973-theology`; same source and system messages and at most
  two claims as the preceding local diagnostic. No reference answer is sent.
- Strict `response_format.json_schema`, medium reasoning, temperature 0, top-p 1,
  one completion, non-streaming; standard tier (no priority/flex parameter).
- Input reservation: 65,536 tokens; generated-token cap: 16,384. Reasoning is billed
  as output; completion usage is not double-counted with its reasoning breakdown.
- Uncached prices: $1.30/million input and $2.60/million output. Worst-case
  reservation: **$0.1277952** before send. Hard authorized ceiling: **$0.25**.
- Maximum one paid attempt, zero retries/fallbacks, no verifier calls. All 28 local
  historical attempts remain counted; cumulative maximum 29, including one paid.
- Timeout scales with request input bound and output cap: startup allowance 120s,
  input bound / 100, output cap / 20, rounded upward to a minute, maximum 1,800s.
  This is an HTTP operation inactivity allowance, not a hard wall-clock deadline.

The dated hosted ID and returned model name are checked exactly. Hosted weight
identity cannot be independently hashed; the manifest states that limitation.
The exact model/schema/medium-reasoning combination is documented but unvalidated
until Brian executes the request. Refusal, unsupported parameters, truncation,
usage overflow or model substitution fails explicitly without another request.

## Credentials and CLI

Use a DeepInfra API key, not SSH. No OpenAI account/key or OpenAI SDK is needed.
The existing `httpx` dependency sends HTTPS directly. The key is read only from
`DEEPINFRA_API_KEY` and used in the Authorization header. Headers and key values
are excluded from frozen manifests, bodies, receipts and reports. Do not put the
key in a command argument, chat, source file or generated JSON.

Get a key from the [DeepInfra dashboard](https://deepinfra.com/dash/api_keys).
In Brian's zsh terminal, read it without echo or a literal secret in shell history:

```sh
read -rs 'DEEPINFRA_API_KEY?DeepInfra API key: '
echo
export DEEPINFRA_API_KEY
```

Prepare without provider access or credentials:

```sh
pte analysis learning-demo model-fit deepinfra-prepare --base-dir /Users/briancummings/Documents/PastorSearchData --from-input /Users/briancummings/Documents/PastorSearchData/evaluation/learning-demo-thinking-check/da1357da33ed6e695989b1f82c7a64bf8dae17925c70adde29ad052bc6d6e308/input.json --json
```

The manifest and `preparation.md` are written under
`<base>/evaluation/learning-demo-deepinfra-fit/<fingerprint>/`. The Markdown contains
the exact `deepinfra-run --experimental --approve-input <fingerprint> --max-usd
0.25 --confirm-prices` command for Brian. `deepinfra-run --input <file> --check-only`
reconstructs all source/history/code/request/budget checks without provider calls;
it reports only whether the credential variable is configured. API credentials,
credit, pricing at execution time and exact contract support are prerequisites,
not validated facts from preparation. Brian confirms the frozen prices at execution.

The fixed TLS endpoint disables environment proxies, redirects and transport
retries. Credential presence is checked before reservation. The shared executor
records a worst-case paid reservation before sending, saves wire content before
decoding and retains the reservation after lost responses. Cached success cannot
cause another call; uncertain or halted attempts block further requests. An
immutable marker assigns the one hosted attempt to its exact frozen input.

## Acceptance and remaining boundary

All raw responses, receipts, results, observations and JSON/Markdown reports stay
under the configured base. Provider reasoning remains separate from final JSON
and cannot warrant a claim. Shared literal compilation, source attribution and
qualification requirements are unchanged. Technical PASS requires complete JSON,
consistent status, nonempty claims and every proposed claim literal-bound.
Independent source/output review is still needed for semantic accuracy; overall
outcome remains INCONCLUSIVE on technical PASS. A component failure is preserved
and stops. No paid retry, additional window, model variant, parallel batch or
full-workflow advancement follows automatically.

This adapter changes neither the original five-minute discovery/minute analysis
geometry nor V8/P1/Scripture commands or production admission. Existing providers
retain their pinned budgets and request policies. DeepInfra uses an explicitly
versioned request and one-attempt ledger rather than expanding those budgets.

Provider references checked October 25, 2026:
[authentication](https://docs.deepinfra.com/account/authentication),
[chat API](https://docs.deepinfra.com/chat/overview),
[strict schema](https://docs.deepinfra.com/chat/structured-outputs),
[reasoning and output billing](https://docs.deepinfra.com/chat/reasoning),
[privacy](https://docs.deepinfra.com/account/data-privacy).

## Generous-output completion baseline

After the first hosted request spent 16,212 tokens on reasoning and stopped at
16,384 total output tokens with partial JSON, Brian authorized one generous-output
request before considering smaller budgets. The API still uses a finite allowance:
65,536 generated tokens, the same medium reasoning, same dated model, identical
source/system messages, same strict schema and at most two qualified claims.

Prepare this explicitly with `deepinfra-prepare --expanded-output --from-input`
pointing to the preserved `583b37a73580f24e234c57a1233effe71f3d60403eeb9d0e1bad97870f424c1e/input.json`.
It writes under `<base>/evaluation/learning-demo-deepinfra-expanded/` and uses the
same `deepinfra-run` CLI, with a distinct request version, namespace and one-attempt
authorization marker on the stopped hosted run. It cannot use the original paid
ledger by accident; version and ledger must match before reservation or send.

The [public model metadata endpoint](https://api.deepinfra.com/models/deepseek-ai/DeepSeek-V4-Pro-0813)
exposes a native `max_new_tokens` schema maximum of 1,000,000, while the general
chat documentation describes 16,384 as the limit for most models. The exact hosted
chat acceptance of 65,536 remains unvalidated until execution. Preparation and
frozen-input verification use one unauthenticated metadata GET to pin the published
deployment version, output capability and uncached prices. No source text or key
is sent in that GET. A metadata/price/deployment change blocks execution. Metadata
requests are reported separately from generation and paid calls. No paid capability
probe or automatic parameter substitution is permitted.

The input reservation is 49,152 tokens, which still exceeds the complete serialized
request's conservative input bound. The new attempt reserves **$0.2342912** under
its **$0.25** ceiling. The prior provider-estimated **$0.0490698** remains separately
recorded and is included in cumulative known list-price usage; $0.25 is the new
attempt's ceiling, not a claim about total historical spend. Maximum one additional
paid attempt; cumulative maximum 30 attempts (28 local, two paid). Unknown spend
still retains its reservation.

The existing budget-aware timeout formula is retained, with a 7,200-second maximum
for this explicit expanded policy. For this source request the calculated HTTP
inactivity allowance is 3,780 seconds (63 minutes), not an expected duration or
an inference-speed guarantee. Earlier versions retain their original timeouts and
limits. Only the generated-token allowance and associated reservation/time budget
change; source text, claim cap, reasoning effort and evidence requirements do not.

First review whether a complete, faithful answer was delivered. Smaller output or
reasoning budgets are future decisions, not an automatic search following this
attempt. The assistant does not execute or monitor the paid source run. No partial
answer is repaired or admitted, and no full-workflow advancement follows.

## Selected Flash 1017 check with reasoning disabled

After Pro's 65,536-token request spent 65,535 tokens on reasoning without a final
answer, Brian approved disabling reasoning and explicitly selected
`deepseek-ai/DeepSeek-V4.1-Flash-1017`. The next preparation uses that exact model
and `reasoning_effort: "none"`. It reuses the same full source window, two-claim
schema, system/source messages, 65,536 output allowance and timeout policy.
Model and reasoning mode both change, so this is a user-selected feasibility
check rather than a controlled comparison attributing improvement to either one.

Prepare through:

```sh
pte analysis learning-demo model-fit deepinfra-prepare --base-dir /Users/briancummings/Documents/PastorSearchData --from-input /Users/briancummings/Documents/PastorSearchData/evaluation/learning-demo-deepinfra-expanded/f1bafae24c11abf0f6fdadb975bade428b94cef517b19a87c2723838e69cefcc/input.json --no-reasoning --json
```

The packet is written under `<base>/evaluation/learning-demo-deepinfra-direct/`.
It freezes public Flash deployment/capability metadata, prices and discount before
execution. Preparation and preflight make one public metadata GET and no generation
calls. A metadata change blocks sending. The public metadata currently reports
a 51% discount but no end date; the October 1–November 1 dates mentioned in chat
are not used as an unverified pricing assumption.

Full uncached prices are $0.20/million input and $0.60/million output. The
reservation is **$0.049152**, with a **$0.05** new-attempt ceiling, even without
promotion. At the currently advertised discounted rates ($0.098/$0.294), the same
maximum usage would cost $0.02408448. Full-list usage and the provider's actual
estimated charge are reported as separate fields; cached-input discounts and
promotional discounts are not invented or used to weaken the reservation.

`preparation.md` contains the exact `deepinfra-run --max-usd 0.05` command. The
resulting request uses a distinct version, namespace and immutable authorization
marker on the completed Pro stop. Any returned model other than the exact Flash
ID is rejected; unexpected reasoning content or a positive reported reasoning-token
count also fails explicitly. Existing length/usage/receipt/no-retry rules remain.
The same literal compiler and qualified observation envelope are used. No result
can grant production admission or automatically launch a follow-up.

Maximum one new paid attempt. All 28 local and two paid attempts remain preserved;
cumulative maximum 31. The 63-minute HTTP inactivity allowance is a budget-derived
waiting allowance, not an expected runtime. Semantic accuracy remains INCONCLUSIVE
until saved source and output are independently reviewed.

## One bounded contract correction

Flash 1017's completed direct response passed the schema, but neither claim bound.
Independent mechanical gaps included ambiguous literal evidence, an invalid
own_assertion/discourse_use pairing, missing evidence for resolved not_stated
findings, and an undefined qualification node. Existing source observations and
the unchanged shared binding compiler cannot repair these producer omissions.
Brian authorized clearer generic instructions and at most one model-authored
correction after a new initial response. Historical outputs remain immutable.

New CLI commands:

```sh
pte analysis learning-demo model-fit corrective-prepare --base-dir /Users/briancummings/Documents/PastorSearchData --from-input /Users/briancummings/Documents/PastorSearchData/evaluation/learning-demo-deepinfra-direct/a0947eb365c5ba0d13b01747075756f47882ec0ce1827c9a9bbd252284144c7c/input.json --json
```

The preparation manifest and exact `corrective-run` command are written under
`<base>/evaluation/learning-demo-deepinfra-correction/<fingerprint>/`. Use that
command with `--check-only` to verify the frozen preparation without generation.
Preparation/checking read public model metadata, verify source/history hashes,
and freeze implementation identity, schema, initial messages and correction
construction. An implementation, metadata or historical-evidence change blocks
execution. An immutable authorization marker prevents assigning a second variant
to the same reviewed predecessor.

This workflow retains the complete P318-R3973-theology window and strict two-claim
schema. It adds explicit compiler rules to the model-facing instructions and
non-repairing field-path diagnostics. The unchanged shared compiler is always
the final mechanical gate. No pastor-specific propositions or warrants are
authored by the preparation code. Mechanical validity does not establish semantic
accuracy; reported viewpoints, adoption, qualifications and interpretations still
need independent review.

The exact model remains `deepseek-ai/DeepSeek-V4.1-Flash-1017`, reasoning disabled.
Each request reserves 49,152 input and 65,536 output tokens at full uncached list
prices. **Both reservations total $0.098304 under the $0.10 ceiling**, regardless
of promotion or cache hits. There are at most two new paid attempts (cumulative
maximum 33: 28 local, five paid). The dynamic HTTP inactivity allowance follows
the existing input/output budget formula; it is not an expected runtime.

A complete response with JSON/schema or literal-binding errors permits exactly
one correction. The original system/source messages remain an identical prefix;
the unchanged failed assistant output and a user message containing frozen
instructions plus all collected diagnostics are appended. The second answer is
a complete model-authored replacement, never a merged or manually repaired answer.
If feedback exceeds the input cap, execution stops without truncation. Timeout,
uncertain spend, refusal, wrong model, unexpected reasoning, transport or length
failures never trigger correction. Empty valid inventories also stop.

Both raw wire responses, exact requests, validation reports and accounting are
preserved. Exact PTE response-cache replay recovers a completed request without
new billing; it cannot create a new answer. DeepInfra prefix caching is automatic
and best effort ([provider documentation](https://docs.deepinfra.com/chat/prompt-caching));
the original prefix is retained but a discount is never assumed. No paid cache
retention option is enabled.

The output separately reports each attempt and final contract fit. Only the final
complete, error-free answer can supply proposed observations. A mechanical PASS
leaves overall semantic outcome INCONCLUSIVE pending source review. A second
validation failure is a component FAIL; there is no third attempt, fallback,
verification call, full-workflow advancement or production admission.
Existing `deepinfra-run`, local model-fit, V8/P1 and Scripture benchmark behavior
is unchanged; old request versions retain their one-attempt policies.

## Explicit field presentation check

The feedback experiment completed one verifier request and returned uncertainty
on every core field, with no selected source passages. No correction ran. The
passage questions had asked the model to locate character ranges in a larger text.
Brian authorized a smaller follow-up, with an explicit instruction not to overfit.

`pte analysis learning-demo model-fit field-check-prepare --from-input <closed-feedback-input> --base-dir <base> --json`
prepares one TypeSafe-only request under
`<base>/evaluation/learning-demo-explicit-field-check/<fingerprint>/`. Its
`preparation.md` contains the exact `field-check-run` command. Both commands
support `--check-only`; preparation and preflight make zero provider calls.
Only `TYPESAFE_API_KEY` is required for execution.

The general presentation rule applies uniformly to both saved claims: include the
exact returned field value in the question, identify its state path, and supply
every complete declared block as literal text in state. Coordinates and hashes
remain for provenance; the model need not calculate text slices. All original
source and proposed bindings remain available. The two fields are qualifications
and polarity, retaining the existing field meanings, Jev 1.13.0 model and 0.90/0.10
thresholds. The actual three-block window produces four field questions and twelve
independent passage-relevance questions, all in one request.

No claim, passage or question is selected by whether it agrees with the prior
review. No pastor-specific examples, expected answers, hand-authored corrected
meanings or prior scores enter the request. Synthetic structural/metamorphic tests
check exact Unicode source copying, uniform field coverage, claim reordering and
renaming, and copying changed proposed values without changing question criteria.
They test the presentation implementation, not semantic model accuracy.

This is a single frozen presentation diagnostic, with no correction, Flash call,
retry, automatic expansion or production admission. Full reservation is
$0.002752512 under a $0.003 ceiling; cumulative maximum attempts 34. Original
results and decisions remain immutable, with a one-variant predecessor marker.
The report preserves raw probabilities and compares every claim/field with the
prior scores. Overall semantic outcome stays INCONCLUSIVE pending source review;
individual field outcomes are model judgments, not established correctness.

Presentation and question count both change, so a changed score cannot isolate
the cause. This previously reviewed window cannot establish calibration or general
accuracy. Any later validation must freeze this question policy before using
existing unseen cases; no additional variant or held-out execution is authorized
by this preparation.

## Re-review from uncertainty alone

Brian authorized one Flash re-review after the explicit-field check remained
uncertain. This tests whether uncertain field scores can prompt a useful source
re-reading without an authoritative critique or supplied correction.

`pte analysis learning-demo model-fit uncertainty-prepare --from-input <completed-field-check-input> --base-dir <base> --json`
freezes the request under `<base>/evaluation/learning-demo-uncertainty-review/`.
The exact `uncertainty-run` command is in `preparation.md`; `--check-only` verifies
the frozen source, history, implementation, provider metadata and budget without
inference. Preparation/preflight read Flash public metadata once, never source
generation. Both provider credentials are required for execution.

The initial two Flash messages and exact saved assistant answer are preserved.
The appended user message contains all four machine field scores with binding ID,
field, existing criterion, probability of correctness, and review_requested for
fields below the existing pass threshold. It explicitly states that uncertainty
does not prove an error, allows an unchanged answer, and asks to preserve supported
content and both underlying points. There are no selected-passage hints, hand-authored
repairs, known-error labels or expected answers. The complete original source
remains available. Flash 1017 uses the existing reasoning-disabled request policy.

After one complete, mechanically valid re-review preserving the two claim IDs,
the exact same explicit-field verification builder checks the revised proposals.
Question wording, field meanings, model, thresholds and full source-block selection
policy are unchanged; the proposed values being checked necessarily change.
There is no extra verifier question or prompt variant selected from the outcome.
A missing claim, schema/binding failure, overflow, timeout, length stop or transport
failure stops without a second re-review or manual repair.

Both original/revised outputs, section-level changes, raw judgments, source references
and accounting are preserved. Changes to previously confident fields are reported
alongside changes to uncertain ones. Source review must examine error correction
AND preservation of correct content. A higher score, unchanged claim ID, or an
unchanged answer cannot establish either. Only qualifications and polarity are
rechecked in this diagnostic; it is not full semantic verification or admission.

Maximum two new paid requests: one Flash re-review and one TypeSafe recheck.
Full uncached reservation **$0.051904512**; ceiling **$0.06**. Cumulative maximum
36 attempts (28 local, eight paid). No new initial extraction, retry, second revision,
automatic expansion or production admission. Overall semantic result remains
INCONCLUSIVE pending review even if all field judgments pass. This reviewed case
does not establish general accuracy, calibration or suitability of a correction loop.

## TypeSafe feedback experiment on the saved Flash answer

The completed `37c64e52...` run bound two claims on its first attempt. Offline
source review found a lost middle-of-the-road qualification and a polarity error
in b2 despite mechanical PASS. Brian authorized a bounded test of verifier
detection and feedback usefulness. No initial extraction is repeated.

```sh
pte analysis learning-demo model-fit feedback-prepare --base-dir /Users/briancummings/Documents/PastorSearchData --from-input /Users/briancummings/Documents/PastorSearchData/evaluation/learning-demo-deepinfra-correction/37c64e52e9a3886d5c9282bcca25ccdb7c924293f2c2d092d033876ad262d7c0/input.json --json
```

The packet and exact `feedback-run` command are written under
`<base>/evaluation/learning-demo-verifier-feedback/<fingerprint>/`. Add
`--check-only` to its run command to revalidate without inference. Frozen inputs
include the original complete source, exact saved response and compiled proposals,
before-verification request, source-range candidates, correction template,
thresholds, schemas, model metadata, historical hashes and implementation hashes.
No human-authored replacement claim, warrant or expected answer is a runtime model
input. Preparation uses one public Flash metadata GET and no inference.

The experiment reuses the existing ten source-verification checks, pinned
`jev-1.13.0`, request/cache/receipt executor and literal compiler. It does not
silently migrate the verifier to a newer model. The live
[TypeSafe API](https://docs.typesafe.ai/api/system-one) and
[Noul contract](https://docs.typesafe.ai/primitives/noul) return probabilities,
not free-text critique. Following the
[citation-check pattern](https://docs.typesafe.ai/cookbooks/citation_check), code
supplies existing source blocks as candidates. Additional independent relevance
questions cover conditions, qualifications, polarity, voice and adoption. Code
selects source-range/hash references at probability >=0.90 and assembles feedback
containing binding ID, failed field, criterion and raw probability. References
are selected passages, not proven error explanations; no selection means inspect
the complete original source. No source words are truncated or synthesized.

Execution is at most three paid requests:

1. TypeSafe evaluates the existing two proposals and candidate passage relevance.
2. If any core check has correctness probability <=0.10, Flash 1017 (reasoning
   disabled) gets one complete correction request. The exact original two-message
   prefix and unchanged saved assistant answer are preserved. The appended feedback
   is proposed judgment, not source authority. A pass or only uncertainty stops
   without generation.
3. If the correction passes mechanical checks and preserves the claim IDs, TypeSafe
   repeats all ten source checks and checks that the same points were corrected
   rather than replaced by unrelated easier claims. The original proposals remain
   explicitly fallible. There is no second correction or automatic advancement.

Each stage has one shared-executor receipt store. Durable attempts, raw responses,
validation and accounting are preserved. Crash recovery replays exact completed
receipts; uncertain spend or any transport/length failure stops. Dynamic correction
and recheck fit are checked before sending, without truncation or extra batches.
An immutable predecessor authorization marker prevents assigning another variant.
`TYPESAFE_API_KEY` and `DEEPINFRA_API_KEY` must both be configured before starting.

The full uncached reservation is **$0.054657024**: two verifier reservations of
$0.002752512 and one Flash reservation of $0.049152. The ceiling is **$0.10**;
promotion and prefix-cache savings are never required. Verifier prices retain
the existing $0.042/million input, free output contract, confirmed in current
[model documentation](https://docs.typesafe.ai/models). Maximum cumulative attempts:
35 (28 local, seven paid). Prior spend remains separate from this new ceiling.

The known b2 qualification and polarity findings are an evaluation-only audit;
they are never sent as expected labels or used to choose runtime corrections.
A diagnostic PASS requires both known errors to be confidently detected and the
correction to pass every final verifier check. A confident miss, mechanical failure,
failed recheck or execution error is component FAIL; uncertainty is INCONCLUSIVE.
Even PASS is specific to this previously reviewed case and requires saved-output
source review. It does not prove verifier independence, accuracy, calibration,
production admission or general extraction recall. Existing CLI behavior is unchanged.
