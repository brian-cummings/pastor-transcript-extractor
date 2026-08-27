# Pipeline diagnostics

Pipeline diagnostics are a read-only observability layer over existing sermon-isolation
artifacts. The canonical product is `diagnostic-trace-v7.json`; Markdown, Mermaid, and
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
and explicit instrumentation gaps. V6 also labels automatic recovery and failures masked
by manual overrides, and evaluates localization, contamination, sermon existence, and final
disposition separately. Its composed overall outcome keeps those component contracts visible.

For reviewed sermons, candidate regret separates three causes that a final recall score
cannot distinguish: the candidate union never covered the sermon (discovery omission), a
better candidate existed but was not selected (ranking loss), or a sufficiently complete
selection lost coverage during refinement. Contamination attribution records the earliest
stage that breached the threshold, any later recovery, stage-to-stage deltas, and whether
the final boundary overreached or clipped the start or end.

V6 includes dimension-aware contract paths and counterfactual stage regret. Contract paths
separately follow localization, contamination, existence, verifier, and disposition from
their earliest breach through recovery or terminal failure. Refinement and arbitration
regret compare persisted alternatives with the chosen output, making quality lost by those
decisions visible without claiming that an unavailable alternative affected production.

Candidate precision analysis evaluates every persisted proposal for coverage,
contamination, boundary error, and duration. Its Pareto frontier distinguishes an overbroad
proposal set from a ranking loss and from a genuine recall/precision tradeoff. Boundary-side
attribution separately measures start overreach, end overreach, and internal contamination,
including their earliest material stage. Automatic and manual-override precision cohorts
remain separate in the systemic evidence.

V7 continues from sermon disposition into operational identity outcomes: current speaker
observation, shadow association attempt, unprofiled evaluation, and effective reviewed
profile membership. Machine outcomes such as `proposed_match` remain proposals rather than
speaker correctness claims. Stale observations are never credited to the current extraction,
and content-terminal, not-attempted, and stale work remain distinct. Persisted association
failures remain visible in the association-outcome branches.

The primary pipeline always uses one mutually exclusive outcome per unique database video.
For identity, the latest persisted association outcome for the current observation supplies
that video's state unless effective reviewed profile membership supersedes it. Repeated
association attempts and boundary advisories are processing-volume metrics shown outside the
population flow; they are never added to unique-video outcome counts.

Identity also connects back as a feedback edge. Persisted `speaker_inconsistent_edge`
evidence is attached to the start or end boundary and compared with the later sermon window.
Existing identity artifacts are advisories, so a later inward or outward movement is reported
as temporal association only. A causal claim requires one persisted adjustment event
containing the pre-adjustment boundary, speaker evidence, decision, and post-adjustment
boundary.

When an advisory remains unchanged and reviewed truth shows material overreach on that same
edge, the trace emits `identity_signal_unconsumed`. This is a diagnostic gap, not permission
to trim automatically: it means the pipeline did not persist whether the signal was ignored,
accepted, rejected, or routed to review.

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

- `diagnostic-trace-v7.json`: durable machine-readable evidence, including a snapshot of
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

By default, this derives a structural trace for every latest extraction artifact in the
database. Matching fixtures enrich those traces with reviewed correctness evidence; runs
without fixtures remain explicitly unreviewed and never receive recall, contamination, or
root-cause correctness claims. Database videos without an extraction record are counted by
processing status. Use `--fixtures-only` to reproduce the narrower reviewed-fixture scope.

The command does not reclassify the corpus. The timestamped result contains per-video traces
and reports plus `system-diagnostics.json` and `system-diagnostics.md`. The systemic Markdown
starts with an all-outcome Mermaid map covering database videos, extraction availability,
valid and missing artifacts, operational dispositions, the reviewed/unreviewed split, and
the downstream identity outcome population. Identity branches show observation availability,
the latest association outcome, effective reviewed profile membership, and the unique-video
subset with feedback advisories. Repeated attempt and advisory event totals appear only in a
separate processing-volume section.
Observed failure counts and root-cause hypothesis counts remain separate. The report also
partitions automatic and manual-override outcomes, reports fixture evaluation partitions,
shows recall and contamination threshold sensitivity for reviewed positives, and summarizes
candidate regret, refinement/arbitration regret, terminal causal stages, join evidence,
identity outcomes, and identity boundary feedback. Unknown fixture partitions remain visible
rather than joining a named cohort.

The identity section also joins current observation stops, profile-readiness topology,
reviewed leave-one-out candidate funnels, and machine-policy blocks into an additive
automation-blocker view. It separates observed blockers from structurally derived next
operations and engineering recommendations. Counts include only persisted current work;
possible memberships or proposals after a repair are explicitly contingent and are not
counted as unlocks. Retrieval failure locations remain observed evidence, while proposed
explanations remain labeled causal hypotheses. Use `--speaker-evidence-root` when reviewed
speaker-pair evidence is stored outside `evaluation/speaker-pairs`.
For current observations with no association artifact, the projection performs
a metadata-only eligibility check. Dispatchable observations remain
`association_not_attempted`; missing media, diagnostic spans, or other
prerequisites are reported separately as
`association_prerequisite_unavailable` with their observed reason codes.

## Compare two diagnostic runs

After deriving a new systemic report from updated existing artifacts, compare it with an
earlier report without running classification:

```bash
.venv/bin/python -m pastor_transcript_extractor.cli diagnose-compare \
  --before evaluation/diagnostics/BEFORE/system-diagnostics.json \
  --after evaluation/diagnostics/AFTER/system-diagnostics.json \
  --output-root evaluation/diagnostics/comparisons
```

The comparison reports fixed, improved, regressed, tradeoff, policy-changed, changed,
unchanged, added, and removed runs, plus failure-signature membership changes. It records
per-dimension transitions, stage-regret transitions, source artifact hashes, and algorithm
versions so a diagnostic interpretation change can be distinguished from an artifact or
pipeline change. V6 adds semantic fingerprints for transcript, discovery, selection,
refinement, arbitration, verifier, disposition, and identity components. Whole-file rewrites
can therefore be labeled as metadata-only rather than behavioral changes. Older reports
remain readable by the comparator, which derives an overall
outcome from their component contracts when necessary.

## Known evidence gaps

Existing artifacts do not persist rejected join attempts or the automatic final output
immediately before a manual override. Each affected trace declares these limitations and
the instrumentation required to resolve them. That keeps missing evidence visible instead
of silently turning it into a causal claim.

Identity artifacts currently persist edge inconsistency advisories but not the adjustment
event that consumed them. Diagnostics therefore surface the evidence and any later boundary
movement while explicitly withholding causal attribution.
