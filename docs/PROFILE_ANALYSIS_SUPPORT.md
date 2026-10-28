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
   constituent caches, durable reservations and receipts, no retry/fallback.
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
output cap, thinking disabled, a finite preflight-derived timeout, and one attempt.
The frozen run enumerates its exact maximum attempts and total reservation before
execution. The current supervised adapter allows at most $0.55 per run and strictly
less than the previously authorized $1 cumulative conservative charge. Unknown
usage retains its reservation and halts further calls. No corpus collection,
classification, reclassification, pastor comparison, ranking or admission occurs.

## CLI

Use `pte docs cli --output <base>/docs/CLI_REFERENCE.md` for the exact current options.
The production-facing group is `pte analysis profile-support` with `prepare`, `run`
and read-only `report`. `prepare` requires `--profile-record`; no user-authored
cases or JSON are required. It emits the exact input path, fingerprint and budget
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
