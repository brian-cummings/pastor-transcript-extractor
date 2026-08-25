# Pipeline diagnostics

Pipeline diagnostics are a read-only observability layer over existing sermon-isolation
artifacts. The canonical product is `diagnostic-trace-v2.json`; Markdown, Mermaid, and
systemic summaries are deterministic projections of that trace.

## Diagnostic model

Each trace records the same contract for every stage:

```text
Input -> Decision -> Output -> Evidence
```

The stages distinguish transcript acquisition, rule comparison, coarse supporting
evidence, candidate envelopes, candidate selection, joining, fine refinement, final
arbitration, recording verification, and disposition. Each stage records its input and
output ranges, boundary movement, duration added and removed, contract status, warnings,
and available evidence.

With a reviewed positive fixture, the trace measures duration-based sermon coverage and
contamination at every stage. Without ground truth, it reports only structural retention
and explicitly makes no recall or contamination claim. Reviewed no-sermon fixtures treat
intermediate candidates as diagnostic evidence and evaluate the final acceptance decision.

`earliest_observed_failure` is kept separate from `root_cause_hypothesis`. The former is a
measurement; the latter is an inference with confidence, supporting evidence, alternatives,
and explicit instrumentation gaps. V2 also labels automatic recovery and failures masked
by manual overrides, and evaluates localization, contamination, sermon existence, and final
disposition separately.

## Single-run diagnosis

This command reads the latest existing `proposed.json` and does not rerun extraction or
classification:

```bash
.venv/bin/python -m pastor_transcript_extractor.cli diagnose \
  --video-id 123 \
  --base-dir /path/to/data
```

Add `--fixture evaluation/fixtures/VIDEO_ID.json` to enable reviewed coverage and
contamination measurements. Add `--output-dir /path/to/output` to avoid writing in the
video artifact namespace.

The command writes:

- `diagnostic-trace-v2.json`: durable machine-readable evidence, including a snapshot of
  the versioned stage contract.
- `diagnostic-report.md`: Mermaid pipeline loss map, static timeline overlay, stage
  transitions, coverage/contamination tradeoffs, and causal assessment.

## Systemic diagnosis

```bash
.venv/bin/python -m pastor_transcript_extractor.cli diagnose-system \
  --fixture-dir evaluation/fixtures \
  --output-root evaluation/diagnostics \
  --base-dir /path/to/data
```

This derives traces only where a fixture and an existing proposed artifact are both
available. It does not reclassify the corpus. The timestamped result contains per-video
traces and reports plus `system-diagnostics.json` and `system-diagnostics.md`. Observed
failure counts and root-cause hypothesis counts remain separate.

## Known evidence gaps

Existing artifacts do not persist rejected join attempts or the automatic final output
immediately before a manual override. Each affected trace declares these limitations and
the instrumentation required to resolve them. That keeps missing evidence visible instead
of silently turning it into a causal claim.
