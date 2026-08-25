# Pipeline diagnostics

Pipeline diagnostics are a read-only observability layer over existing sermon-isolation
artifacts. The canonical product is `diagnostic-trace-v3.json`; Markdown, Mermaid, and
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
and explicit instrumentation gaps. V3 also labels automatic recovery and failures masked
by manual overrides, and evaluates localization, contamination, sermon existence, and final
disposition separately. Its composed overall outcome keeps those component contracts visible.

For reviewed sermons, candidate regret separates three causes that a final recall score
cannot distinguish: the candidate union never covered the sermon (discovery omission), a
better candidate existed but was not selected (ranking loss), or a sufficiently complete
selection lost coverage during refinement. Contamination attribution records the earliest
stage that breached the threshold, any later recovery, stage-to-stage deltas, and whether
the final boundary overreached or clipped the start or end.

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

- `diagnostic-trace-v3.json`: durable machine-readable evidence, including a snapshot of
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
failure counts and root-cause hypothesis counts remain separate. The systemic report also
partitions automatic and manual-override outcomes, reports fixture evaluation partitions,
shows recall and contamination threshold sensitivity, and summarizes candidate regret and
join evidence. Unknown fixture partitions remain visible rather than joining a named cohort.

## Compare two diagnostic runs

After deriving a new systemic report from updated existing artifacts, compare it with an
earlier report without running classification:

```bash
.venv/bin/python -m pastor_transcript_extractor.cli diagnose-compare \
  --before evaluation/diagnostics/BEFORE/system-diagnostics.json \
  --after evaluation/diagnostics/AFTER/system-diagnostics.json \
  --output-root evaluation/diagnostics/comparisons
```

The comparison reports fixed, regressed, changed, unchanged, added, and removed runs, plus
failure-signature membership changes. V2 reports remain readable by the comparator, which
derives an overall outcome from their component contracts when necessary.

## Known evidence gaps

Existing artifacts do not persist rejected join attempts or the automatic final output
immediately before a manual override. Each affected trace declares these limitations and
the instrumentation required to resolve them. That keeps missing evidence visible instead
of silently turning it into a causal claim.
