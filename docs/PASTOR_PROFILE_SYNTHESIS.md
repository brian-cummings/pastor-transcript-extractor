# Local editorial synthesis of the pastor profile

This optional layer writes a natural pastor-level portrait from the existing V5
claims and reviewed local descriptions. It does not reread full transcripts,
reclassify passages or establish new theology. The original profile remains intact.

Inspect the bounded request without model probes, generation or writes:

```bash
pte analysis profile-synthesis --prepare --json
```

Brian runs the single bounded synthesis request:

```bash
pte analysis profile-synthesis --run --json
```

The current configured installed local Ollama model is used. No model is pulled
or switched automatically. The run pins the model digest before generation and
checks it afterward. Limits: one generation per exact prepared packet, temperature
0, context 32,768, output 3,072 tokens and request timeout 180 seconds. Oversized
inputs fail preparation; evidence is never silently truncated to fit. Preparation
reports the configured model and budgets without contacting Ollama.

The new `index.html` places a clearly labeled synthesis draft above the existing
profile and full source evidence. Companion `synthesis-v1.md`, `review-v1.json`,
`raw-response-v1.json`, `source-profile-v5.json`, backend pin and request ledger
are under the configured app base in `evaluation/pastor-profile-synthesis-v2/`.
The response receipt retains token counts, model duration and wall time when
available; these are not claims of measured product parity or cost savings.

Every generated sentence cites short source handles constrained by the response schema.
Code maps those handles back to the exact existing claim IDs for the evidence links
and audit record. The model does not have to reproduce long hash-based identifiers. Supplied local readings retain
speaker/use, scope, conditions, qualifications and unknowns. The model receives no
raw transcript windows or probability inventory. Exact reviewed explanations
replace redundant generic summaries where their support sets coincide; the full
original record is still available beneath the draft.

“Who they are most like” remains explicitly unavailable: no validated benchmark
inputs or comparison method are supplied. What stands out describes these
recordings, not uniqueness against other pastors. Confidence is a code-owned
description of sample coverage and limitations; no LLM score or percentage appears.
The four existing analytical families remain; omitted synthesized sections retain
an unavailable message and their underlying evidence/unknowns.

After the run, inspect cached output without another model request:

```bash
pte analysis profile-synthesis --json
```

Verify cached reconstruction without network or writes:

```bash
pte analysis profile-synthesis --check-only --json
```

Schema/citation validation checks structure and source pointers. It cannot prove
that wording is entailed, that several findings form a coherent argument, or that
qualifications survive a paraphrase. A structurally valid output therefore remains
`DRAFT_AWAITING_SEMANTIC_AND_WORDING_REVIEW`. Codex checks each sentence against its
cited evidence and recommends acceptance or specific corrections; Brian reviews
the concrete prose. No acceptance, benchmark, new measurement or production
projection occurs automatically.

Malformed, incomplete, unknown-citation and output-limited responses are withheld,
with raw receipts retained. A timeout or digest drift does not trigger retries,
prompt repair, model switching or fallback. A failed request requires inspection
and a concrete decision; running the command again cannot silently repeat it.
Cached reuse retains the original generation receipt and reports zero new calls.

The normal V5 description command stays provider-free. No quotation extraction,
broader collection, new measurement/admission, comparison/ranking or ministry-wide
stability claim is released by this editorial task. The Henry Johnson example is
a readability reference, not a target whose judgments should be reproduced.

Focused checks:

```bash
python -m unittest discover -s tests -p 'test_profile_synthesis.py'
```

## Inspected first run — 2026-10-21

The first run is rejected, not awaiting another execution. Panel
`d40b9159249df6f35bbe3e2afc3c66329b874cc4e633fed51713f3dd8756b855`
produced review fingerprint
`4c27cbb617686fc657c20be7b864e6aefdda437c7837125b5b226326fefc507f`.
The raw output contains only `theological_orientation`, with three sentences.
The first two copy supplied S1/S2 descriptions. The third changes topic attention
into an inferred consistent emphasis, and uses plural “preachers.” It is not accepted.

The exact structural rejection is `A unique portrait section is required`.
Ollama stopped normally (`done_reason=stop`); this was not output truncation.
Receipt: one generation, two metadata reads, 5,863 input tokens, 147 output tokens,
26.409 seconds model duration. No additional model request was made for review.

The request prompt required portrait presence, while its JSON schema allowed any
section. Post-response validation correctly caught this mismatch. The proposed
next change is a versioned contract requiring a portrait property in the generation
schema, keeping citations and semantic review intact. That is a concrete proposal,
not an executed variant or a promise of better prose; Brian must decide before
another experiment. Keep V5 and the original rejected response. The cached commands
above remain available for inspection and do not rerun the model.

## Approved V2 correction — 2026-10-21

Brian approved the required-portrait correction. The current CLI now prepares V2:
`portrait` is a required, nonempty array of cited sentences; optional `sections`
cannot contain another portrait. Code normalizes that structure for the existing
renderer without altering generated wording. Inputs, configured model, budgets,
citation rules and semantic acceptance checks remain unchanged. Nine focused mock
tests pass, including the original missing-portrait failure shape, empty portrait
and attempted duplicate portrait. V1 files remain in their original directory;
the `*-v1.json` receipt filenames within V2 describe the unchanged receipt format.

Run `pte analysis profile-synthesis --prepare --json` and then
`pte analysis profile-synthesis --run --json`. Codex has made no model or metadata
calls for this revision. A valid portrait still requires sentence-level semantic
and readability review; this correction alone promises neither fidelity nor quality.

## V2 run and semantic review — 2026-10-21

Brian explicitly authorized Codex to execute and check the small V2 request.
It ran once with `gemma3:4b`: 5,872 input tokens, 377 output tokens, 34.017 seconds
model duration, one generation and two metadata reads. The required portrait is
present; the structural status is `DRAFT_AWAITING_SEMANTIC_AND_WORDING_REVIEW`.
The separate reviewed verdict is **REJECT_SYNTHESIS_KEEP_V5**.

All six generated entries copy a source description and add an unsupported
interpretation. Attention to grace does not establish affirmed unearned salvation;
attention to faith does not establish evangelical alignment; transformation topic
presence does not establish a consistent exhortation or salvation mechanism.
The remaining entries similarly add breadth, motive or disposition. Only S1–S6
were cited; the richer reviewed descriptions were not used. Do not repair these
claims by relabeling the existing measurements or silently citing different sources.

The original raw response and draft remain unchanged. Separate
`semantic-review-v1.md` and sealed `semantic-review-v1.json` in the V2 run directory
record each copied supported prefix, unsupported addition, cited source and limit.
Panel: `ada8c143376fda95d6deb741ee313e7b6b5c9fdb6deca99eb4c45cd3dad757ae`.
Semantic review: `7bb1c0b9ae7f3d0fad811b3bc56b482286b476c8aa7dc45cc07e0139e9d68d99`.
The original HTML remains an explicitly unaccepted draft; use the semantic review
for the reviewed verdict. Cached CLI status reports structural validity only.

Keep V5 and withhold this synthesis. No retry or further variant was started.
Any further experiment needs a specific decision; quality/economics parity remains
unmeasured. Review itself made no provider or metadata requests.
