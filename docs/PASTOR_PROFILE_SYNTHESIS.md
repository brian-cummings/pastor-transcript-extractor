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
are under the configured app base in `evaluation/pastor-profile-synthesis-v1/`.
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
