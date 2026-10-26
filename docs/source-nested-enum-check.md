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
