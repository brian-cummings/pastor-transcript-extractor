# Profile analysis support

The penultimate stage consumes an already assembled profile and produces the
support record consumed by final document assembly. It is not a new sermon
extractor or a replacement for category/leaf analysis. The shared implementation
is `profile_analysis_support.py`; the CLI/storage adapter is
`profile_analysis_support_execution.py`.

## Active implementation sequence

1. **Shared evidence/claim boundary and document handoff — implemented.** Enumerate
   every reader claim, validate exact source, measurement, question/model, sample
   membership and bounded context. Reuse existing qualified bound records and
   deterministic aggregate summaries with their existing status. Preserve explicit
   missing-evidence gaps. Exit: focused pure-core tests and alternate profile IDs.
2. **Bounded request execution and pipeline CLI — implemented.** One Qwen3.8-27B
   instant request per eligible claim; complete input and schema preflight, exact
   constituent caches, durable reservations and receipts, and one budgeted streaming-whitespace retry without model fallback.
   Exit: stubbed whole-profile, cache/recovery, lost-response, budget, citation,
   dependency and withheld-result checks. No live corpus run during development.
3. **One real-profile validation — prepared separately under application base.**
   Brian runs the exact frozen command. Review statement support, attribution,
   qualifications, counterevidence, unknowns, document usefulness and cost. Exit:
   report demonstrated errors/gaps and recommend the smallest responsible remedy;
   no automatic next experiment or threshold changes.

## Pipeline contract

The pure `build_plan(record)` accepts an assembled profile record; no profile ID,
recording ID, human-authored reference reading or historical experiment is
required by the core. The initial CLI accepts an existing profile JSON artifact.
The current validation input is a real historical profile containing authored
candidate prose and some authored upstream proposals. Those remain the objects
and inputs under assessment, not independent accuracy references or a requirement
that future profiles be authored by humans.

Each request contains the candidate statement and scope, its complete declared
measurement input set, stored upstream aggregates, linked supporting and contrary
passages, and compatible existing voice/adoption/polarity/condition/qualification
records. Bounded context is a named field with its own coordinates. Context is
never relabeled as actual target speech or given fabricated timestamps. All
compatible declared constituents are retained; context overflow is an explicit
unresolved gap, not silent truncation or an automatic extra call.

Qwen returns `supported`, `contradicted` or `unresolved`, a brief reason, selected
source-unit citations and any necessary qualifications with citations. Code checks
literal identity and contract fit. Model support is not semantic ground truth,
calibrated confidence or production admission.

The final handoff enumerates every original statement. Only an unchanged supported
statement without extra required qualifications and with supported dependencies
appears in `ready_claim_ids`. Its declared scope, limitations and alternative
explanations remain attached in the document entry and readable handoff. Contradicted, qualified, unresolved, failed and not-run
statements remain visible, together with inherited profile gaps. The consumer does
not author repairs, new positions or interpretive warrants. Cycles and unresolved
parents cannot become a supported final conclusion.

## Storage, caching and budget

Run artifacts live under `<base>/evaluation/profile-analysis-support-v1/<run-id>`.
Exact request receipts live in the existing shared accounting namespace
`<base>/evaluation/qualified-observations/<request-id>/execution`. This lets a
presentation/run identity change reuse unchanged compatible requests without
copying paid attempts or double-counting cost. Source, candidate, question, schema,
model or decoding changes invalidate the affected constituent request.

Input reservation tiers are conservative UTF-8 byte bounds plus framing, not model
tokenizer counts: 16,384, 32,768, 65,536 or 131,072. Each request has a 2,048-token
output cap, thinking disabled, and a finite preflight-derived timeout. Newly prepared
Qwen requests use streaming recovery with at most two physical HTTP attempts,
reserved within the existing per-request dollar ceiling. If that ceiling cannot
cover both attempts, cancellation still works but recovery is disabled.
The frozen run enumerates its exact maximum attempts and total reservation before
execution. The current supervised adapter allows at most $0.55 per run and strictly
less than the previously authorized $1 cumulative conservative charge. Unknown
usage retains its full reservation. A closed whitespace cancellation followed by a
complete recovery may continue within that reservation; other unknown usage halts
the batch. No corpus collection,
classification, reclassification, pastor comparison, ranking or admission occurs.

## CLI

Use `pte docs cli --output <base>/docs/CLI_REFERENCE.md` for the exact current options.
The production-facing group is `pte analysis profile-support` with `prepare`, `run`
and read-only `report`. `prepare` accepts `--profile-record` or
`--validation-from <saved-run-directory>`; no user-authored cases or JSON are required. It emits the exact input path, fingerprint and budget
for `run`. `run --check-only` verifies frozen identities without generation.

The older `pte analysis learning-demo profile-support-*` one-statement diagnostic
remains available and unchanged. Existing V8/P1 generation and Scripture benchmark
commands retain their behavior.

## Outputs and admission boundary

`results.json` preserves each judgment, receipt reference, accounting and execution
outcome. `document-input.json` is the typed seam for the final document stage;
`analysis-support.md` is the readable support handoff, including withheld claims
and inherited limits. Final prose generation is not activated by this stage.

The core explicitly rejects production consumption while its output is not
admitted. Experimental execution is a release-policy setting around the same
contracts and composition code, not a separate semantic implementation. Routine
per-statement human approval is not a runtime requirement. Source review is the
bounded validation activity before any later release decision.

## DeepInfra Qwen streaming recovery

`deepinfra_streaming.py` assembles OpenAI-compatible SSE internally, retaining the
existing nonstreaming response interface. `PTE_DEEPINFRA_WHITESPACE_THRESHOLD`
sets the initial threshold (default 256); new request identities freeze that value.
Only consecutive JSON whitespace outside a quoted string triggers cancellation;
string escape state persists across chunks. The response and client pool close
before retry begins. An identical request, including temperature and schema, may
be sent once more. Retry uses the remaining original timeout, not a fresh timeout.
Other incomplete, refused, malformed, HTTP-error or disconnected responses are not
automatically retried by this mechanism.

Before any send, the shared executor durably reserves the full permitted recovery
cost. Each physical attempt has its own reservation, partial wire output and
telemetry under `stream-attempts/<request-id>/<number>`. Latency, cancellation,
usage availability, connection closure and retry outcome are retained. Only the
last complete response can become a successful cache receipt. Cancelled/incomplete
outputs remain failed evidence, never successful cache entries. The shared usage
account counts both physical attempts, includes only final known usage in measured
cost, and retains the full reservation for unavailable cancelled usage. Closing a
client connection does not prove that the provider bills zero further tokens.

Existing frozen request versions and receipts retain their original reservations;
legacy Qwen requests stream with cancellation but cannot acquire an unreserved
second attempt. Newly prepared profile requests carry an explicit `-stream-v1`
identity. Maximum paid attempts now counts physical requests. No dollar ceiling
has been raised: a complete profile with retry reservations may no longer fit its
old budget, in which case preparation stops. New execution needs a fresh frozen
input and an adequate separately authorized budget/scope, not an automatic rerun.

Inspect settings without network or generation with
`pte analysis profile-support transport-info --json`.

Protocol reference: [DeepInfra streaming](https://docs.deepinfra.com/chat/streaming).

## Citation and qualification contract V2

Each complete source unit receives one opaque `citation_id`, resolving to exactly
one passage, field and unit. The model selects those IDs instead of independently
selecting passage/field/start/end combinations. All necessary units can be cited;
no source sentence is shortened to satisfy a word limit. Supported and contradicted
answers require evidence in both the JSON schema and the local validator.

Source-backed qualifications distinguish `already_preserved`, `missing_required`
and `unresolved`. `already_preserved` requires a literal excerpt from the supplied
statement, scope or declared caveats; code preserves every matching offset. This
proves the excerpt exists, not that the model's entailment judgment is correct.
Only qualifications judged already preserved can leave an otherwise supported
statement available. Missing requirements, uncertainty and unassessed dependencies
remain withheld. Legacy answers with qualifications keep their original withholding
behavior; old results and receipts are never silently upgraded.

`prepare --validation-from` freezes four previously exposed cases selected by a
fixed mechanical policy: first lexical saved whitespace-loop failure, invalid
citation combination, supported style example with qualifications, and unresolved
answer. It retains original cases, complete evidence and dependencies, with hashes
of the prior input, results and selected receipt/wire pairs. No expected semantic
answers or corrected pastor wording enter requests. Unselected dependencies remain
unevaluated. The report labels selected versus assembled counts; this is contract
regression validation, not a full-profile run or independent accuracy benchmark.
The bounded packet has a $0.12 run ceiling, at most eight physical attempts, and
the same strict cumulative $1 limit. It does not automatically advance the workflow.
