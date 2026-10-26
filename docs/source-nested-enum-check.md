# Synthetic nested adoption-field diagnostic

The source-context continuation completed its first window's binding repair and
TypeSafe recheck. The next window stopped after generating a partial address-act
record ending at `claims[0].address_acts[0].adoption`, followed by 65,459 CR/LF
characters. The saved provider usage reports 65,536 completion tokens and zero
reasoning tokens. That output identifies the point of failure; it does not prove a
model/decoder cause.

The reader schema uses an adoption string for an address act and an adoption object
for a claim. Their meanings and vocabularies are retained. A small synthetic request
exercises both nested fields and the address's addressee. Its compact field/type/enum
guide is generated from the schema, with no manually duplicated vocabulary. The
strict schema is supplied once through `response_format`. The synthetic speaker
addresses gardeners; no pastor source, fingerprint, reference reading, saved source
answer or TypeSafe call is a runtime input.

This is one guided request with a reduced schema, not a controlled baseline
comparison. PASS means the exact synthetic case completed, passed structural checks
and represented the known synthetic roles correctly. It establishes neither source
accuracy nor the cause or resolution of the earlier stall. A failure does not
establish that every model or structured-output request will fail.

The pinned Flash 1017 request keeps reasoning disabled, permits at most 1,024 output
tokens and makes no retry. It reserves $0.0022528 at uncached, undiscounted rates
under a $0.003 ceiling, with at most 39 cumulative paid attempts including history.
No source trial is resumed or automatically advanced afterward.

The CLI entry points are `pte analysis learning-demo model-fit deepinfra-enum-prepare`
and `deepinfra-enum-run`. Prepare takes `--from-input` with the stopped source-context
input, validates its accounting and current public deployment/prices, and emits the
exact execution command. Run accepts `--check-only` for read-only frozen-input
validation; execution requires `--experimental`, the exact `--approve-input`,
`--max-usd 0.003`, `--confirm-prices` and the DeepInfra credential. Brian executes
the paid command. All inputs, raw responses, receipts and reports go under the
configured application base in `evaluation/deepinfra-nested-enum-check/<fingerprint>`.

PTE currently sends no provider cache key, TTL or paid retention option. DeepInfra's
automatic prefix cache is best effort; the provider documents a separate paid
retention option of five minutes or one hour. PTE's immutable exact-response cache
has no TTL and skips the provider entirely when compatible receipts are reused.
Reservations never assume provider cache discounts. See DeepInfra's
[retention policy](https://deepinfra.com/blog/prompt-cache-retention).

## One full-schema source follow-up

After the synthetic PASS, `guided-source-prepare` freezes the previously failed
P318-R281 application window with the unchanged full reader schema and the same
mechanically derived guide, now covering all full-schema fields. It preserves the
complete frozen source message and geometry. Flash 1017 remains reasoning-disabled;
this small follow-up caps output at 8,192 tokens. A single TypeSafe check of
qualifications, polarity and context follows only after schema and binding pass.
There is no binding retry or semantic correction in this follow-up. The two-request
reservation is $0.017498112 under a $0.02 ceiling, and cumulative paid attempts remain
at most 41. `guided-source-run --check-only` validates the freeze without inference.

The schema guide and output cap both change relative to the stalled request, so
this is a feasibility follow-up, not an isolated causal experiment. Binding PASS
remains separate from semantic accuracy and production admission. Brian explicitly
authorized Codex to execute this small follow-up, overriding the normal command-only
handoff for these two requests; that authorization does not launch the remaining
windows or the full demonstration workflow.

The full-schema follow-up completed normally in 1,390 output tokens, but its saved
answer failed binding: two ambiguous literal references and one undefined
qualification node. Passing that frozen input to `guided-source-prepare` now
prepares the separately authorized single binding correction. It reuses the exact
paid answer and compiler diagnostics as model context, retains the original
system/source prefix, and enforces binding-ID coverage. The initial answer is not
regenerated or repaired by code. One new replacement and one conditional TypeSafe
check are reserved within $0.02, with no further retry and no automatic source
expansion or admission. Brian explicitly authorized Codex to execute this correction
as well.

The next feedback version, `binding-feedback-facts-v1`, enriches existing compiler
errors without changing their meanings or acceptance checks. Literal errors include
every exact occurrence, Unicode target and block-local coordinates, source hashes
and bounded literal surroundings. No occurrence is selected; the full original
source remains available. Qualification-reference errors include the referenced ID,
whether it exists, all saved node IDs and roles, and the required role/proposition
pairing. Saved roles are explicitly marked as model proposals, not verified facts.
No node is selected or rewritten. Unknown diagnostic types remain verbatim.

`guided-source-prepare` accepts the failed correction's frozen input to prepare one
further explicitly authorized correction with these facts. It preserves the latest
complete answer and original system/source prefix, and replaces superseded generic
mechanical feedback with the current enriched errors. No historical answer, receipt,
binding contract, quotation rule, threshold or production admission is changed.
