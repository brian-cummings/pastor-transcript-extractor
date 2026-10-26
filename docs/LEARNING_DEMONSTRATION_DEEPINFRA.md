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
