# One-window local thinking diagnostic

**Historical bounded development workflow (status clarified 2026-11-01).** Recorded authorization, budgets, selected models and retry decisions apply to the runs described below. This is not the current goal/next-run queue. Follow the [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md), [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) and [section delivery](PROFILE_SECTION_DELIVERY.md); preserve original receipts and do not replay old commands as a successor experiment.

The reviewed runtime-repeat failed at two different boundaries: the first window
was schema-valid but its proposition referenced an undefined evidence node, and
the second window was still generating at roughly 13 tokens/second when the
600-second HTTP timeout cancelled it. Offline review also identified attribution
and meaning omissions in the first answer. A timeout change alone cannot resolve
those extraction problems.

Reuse inspection followed the frozen source request, saved wire response,
literal-evidence compiler and stopped-run accounting. The complete first window
and current Qwen weights are reused. The former six-window runs remain closed.
No source answer, expected doctrine, prior model answer or hand-authored warrant
is inserted into a request. The new prompt only makes the existing node-reference
invariant explicit and changes the claim cap.

Brian requested a smaller test, thinking and a dynamic timeout. The bounded next
slice is one complete, previously reviewed window (`P318-R3973-theology`) with
at most two complete claims. Source text is byte-identical to that request. The
qualified observation structure, literal locator and binding compiler remain the
same; the diagnostic schema reduces the maximum claim count from twelve to two.
The existing saturation/unknown outcomes remain available. This is a diagnostic
on a known failure, not an independent accuracy benchmark, coverage measurement
or controlled test of thinking alone.

The native Ollama request uses `think:true`, a 4,096 reported generated-token cap
and the same deterministic sampling parameters. Provider thinking content is
preserved in raw wire responses and receipts, separately from the final JSON.
It never becomes source evidence or an interpretive warrant. A completed trace
does not establish correctness. A length stop is an explicit component failure;
it does not trigger a continuation or retry. Token usage uses provider counts;
no separate reasoning/final-answer token split is invented.

The frozen timeout policy adapts to each serialized request budget:

```
input_bound = serialized UTF-8 bytes + 4096 framing
allowance = 120 + input_bound / 100 + output_cap / 8 seconds
timeout = round allowance upward to a whole minute; minimum 300 seconds
```

A request needing over 1,800 seconds is rejected during preparation. The rates
are conservative planning assumptions, not a speed guarantee. The timeout is
HTTPX's network-operation inactivity allowance, not a hard wall-clock deadline;
it is not extended during execution. Existing frozen request versions retain
their disabled-thinking policy and 600-second timeout. Only the new diagnostic
request version and namespace can enable this policy. Cache and receipt identity
include the policy, thinking setting, schema, model files and server version.

Prepare through the PTE CLI:

```sh
pte analysis learning-demo model-fit thinking-prepare --base-dir /Users/briancummings/Documents/PastorSearchData --from-input /Users/briancummings/Documents/PastorSearchData/evaluation/learning-demo-model-fit/44be6c3265a426ef9197e94cfa66830a5ed9cb9ac7af3fc712978335b0f4efca/input.json --json
```

Preparation validates the preserved history, unchanged source/compiler contracts,
same installed Qwen model and reviewed Ollama 0.40.11 server. It writes its exact
`thinking-run` command in `preparation.md` under
`<base>/evaluation/learning-demo-thinking-check/<fingerprint>/`. Use
`thinking-run --input <returned-file> --check-only` for provider-free reconstruction.
Brian executes the separately explicit experimental run command. An immutable
marker on the prior stopped run assigns this one attempt to its exact input.

Maximum one new local attempt and zero paid attempts. Prior accounting retains
23 source attempts plus four synthetic conformance attempts; cumulative maximum
28. Lost responses consume the attempt and cannot be resent. Runtime version is
checked before sending. Completed results, raw responses, observations, Markdown
and JSON reports stay under the application base. No runtime repairs, routine
approvals, model fallback, additional windows or production admission.

Acceptance: complete response, strict small schema, consistent status, nonempty
claims and every claim accepted by the existing literal compiler. Technical
contract-fit PASS still leaves overall semantic accuracy INCONCLUSIVE pending
independent source/output review. Report whether a thinking trace was actually
returned. No retry or full-workflow advancement follows automatically. The
responsible insertion points are request execution for the time allowance and
source production for thinking/node references; downstream prose cannot repair
any remaining meaning or attribution failures.
