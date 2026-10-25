# Synthetic Ollama schema conformance

`pte analysis learning-demo runtime-check` prepares two synthetic requests using
the existing request, reservation, receipt and native `/api/chat` transport code.
It does not resume the closed six-window source trial, read sermon data, change
source prompts, repair outputs, build fingerprints or admit evidence.

The cooperative probe requests the supplied schema. The conflicting probe asks
for plain text while the same schema requires a fixed nested JSON object. Both
retain the selected model's frozen `think:false`, deterministic decoding and
existing 8,192 output-token cap. Expected answers are tiny; the cap is retained
to avoid changing the shared executor contract during diagnosis. Maximum two
local attempts, zero paid calls, no retry or fallback. Each probe uses a separate
synthetic case identity, never a source-reading cache identity.

Prepare without generation:

```sh
pte analysis learning-demo runtime-check --base-dir /Users/briancummings/Documents/PastorSearchData --model qwen3.5:9b --json
```

The command returns an exact input path under
`<base>/evaluation/ollama-schema-conformance/<fingerprint>/input.json`. Execute
that file with `runtime-check --base-dir <base> --input <returned-path> --execute
--json`. No fingerprint authoring or manual edits are needed. Installed model
files, server version, request bodies and implementation hashes are frozen and
rechecked before execution. A changed runtime requires new preparation and an
explicit invocation against its new input. Existing results and receipts remain
immutable. A completed invocation returns its saved result; an interrupted
attempt without a receipt cannot be resent.

`input.json`, `execution/attempts`, `execution/wire-responses`,
`execution/receipts`, `result.json` and `report.md` stay under the application base.
`PASS` means both responses met this small schema. Any returned schema violation
is `FAIL(component)`; a transport/completion failure without a conclusive schema
failure is `INCONCLUSIVE`. A PASS is not proof of general grammar enforcement or
pastoral extraction accuracy. This command never automatically advances to a
source trial. Failure calls for addressing the runtime before another source run.

## Evidence and smallest responsible next step

The blocked behavior is reliable delivery of schema-conforming machine source
observations. The saved Qwen trial
`392a9b6f0bb8ffc129a38a562fc8feb13469a80d4fc47ba1d1b85f1473ff9d78`
completed all six requests normally, but returned three JSON syntax failures,
two duplicate-key failures and one schema-field failure. Its zero accepted claims
does not mean the model emitted no claims. Binding and semantic accuracy remain
unassessed for those rejected responses.

Inspected reuse paths: the frozen requests contain the raw schema in `format`;
PTE posts that body directly to local `/api/chat`; saved wire responses preserve
the malformed content before parsing; the strict consumer correctly rejects it.
The installed Qwen config declares the `qwen3.5` renderer/parser and thinking
capability. No missing evidence is repaired downstream.

In the version-tagged [Ollama 0.31.1 chat route](https://github.com/ollama/ollama/blob/v0.31.1/server/routes.go),
the built-in parser path initially suppresses `format` for thinking-capable
models and activates it after observed thinking followed by answer content.
Its immediate-format exception names Gemma4, leaving disabled-thinking Qwen
susceptible to never activating the schema. This is a source-based explanation
consistent with the saved failures, not a traced observation of internal server
state. [Ollama issue 14645](https://github.com/ollama/ollama/issues/14645)
describes the same disabled-thinking Qwen schema problem. Historical issue
closure alone does not establish that an installed build handles this path.

The exact missing information is whether this installed model/server combination
enforces even a small nested schema under the frozen disabled-thinking mode.
The responsible insertion point is the Ollama serving/parser boundary, before
the evidence compiler. The smallest immediate change is this isolated CLI probe.
Acceptance requires both synthetic responses to pass strict JSON and schema
checks, with exact wire receipts and no extra attempts. If it fails, recommend a
verified upstream runtime fix or narrowly scoped serving-path correction before
proposing another separately authorized source trial. Do not silently enable
thinking, change models, upgrade Ollama, relax validation or retry the source run.

## Authorized source repeat after the runtime repair

Brian's two-probe check on Ollama 0.40.11 passed, including the conflicting
instruction, after the same check failed on 0.31.1. He separately authorized one
repeat of the same six source windows. Prepare it through:

```sh
pte analysis learning-demo model-fit prepare --base-dir /Users/briancummings/Documents/PastorSearchData --from-input /Users/briancummings/Documents/PastorSearchData/evaluation/learning-demo-model-fit/392a9b6f0bb8ffc129a38a562fc8feb13469a80d4fc47ba1d1b85f1473ff9d78/input.json --runtime-repeat --json
```

This narrowly scoped preparation requires the exact saved before/after checks,
the completed six-response Qwen schema failure and the same installed model as
the passing check. Every source request body must match the original Qwen trial,
including prompts, schemas, output limit and disabled thinking. Server version
is added to request provenance/cache identity and checked before each send.
Preparation freezes all prior attempt/receipt/wire evidence; an immutable marker
on the prior Qwen run assigns the one repeat to its exact new input at execution.

Maximum six new local requests, zero paid requests; accounting retains 21 source
attempts plus four synthetic attempts, cumulative maximum 31. No automatic retry,
repair, verification calls, downstream comparisons or production admission.
`preparation.md` contains the exact execution command. Brian executes it. The
result compares saved prior Qwen contract diagnostics with the new diagnostics;
no prior answers or conformance results are sent to the model. A contract-fit
PASS still leaves semantic accuracy INCONCLUSIVE.
