# Evidence-supply review navigation

The current work is [the existing-pipeline trace and cleanup plan](evidence-pipeline-trace-v1/REVIEW.md), dated 2026-10-19. It retains the minute-block pipeline and identifies the exact nomination/context handoff that remains to be designed. No replacement model or provider experiment is selected by that review.

| Material | How to use it now |
|---|---|
| `evidence-pipeline-trace-v1` | Current integration findings and concrete cleanup plan. |
| `context-extraction-probe-v1` | Historical, **unexecuted** OpenAI-dependent probe. Zero provider requests; do not treat it as a result or silently substitute Ollama. The trace recommends explicit supersession before detaching its runtime. |
| `context-evidence-architecture-v1` | Earlier standalone extraction hypothesis; integration framing is superseded by the pipeline trace. No feasibility result exists. |
| `collector-retrieval-repair-v1.1`, `collector-retrieval-implementation-v1`, `collector-retrieval-design-v1` | Historical closed collector design, execution and failure evidence. No further tuning/run is proposed. |
| `fresh-discovery-readiness-v1`, `v2`, `v3` | Historical development/confirmation records with their original failures and limitations preserved. Not fresh sources for another confirmation. |
| `source-unit-repair-v1` | Frozen development repair/support and its source audit; retained, not an operational-readiness PASS. |
| Earlier evidence-supply, measurement and admission packets | Historical decisions/contracts. In particular, V4 raw FAIL/containment HOLD and bounded A1 PASS retain their original scopes. |

These folders contain immutable cross-references and hash pins. Their presence does not mean an active recommendation. Consult the current trace before following dated execution instructions. Cleanup is staged and dependency-aware; no historical packet or generated evidence has been deleted or moved.
