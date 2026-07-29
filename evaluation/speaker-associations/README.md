# Speaker Profile Shadow Association

This directory defines the non-mutating bridge from reviewed speaker profiles
to corpus-scale sermon association. It answers:

> Which existing reviewed profile, if any, is supported by multiple acoustic
> comparisons for this unassigned sermon observation?

The command is:

```bash
pte identity shadow-associate-speakers \
  --all-eligible \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Use `--plan-only` first to inspect profile and corpus eligibility without
executing the acoustic model. Use `--youtube-video-id VIDEO_ID` instead of
`--all-eligible` to evaluate one sermon. `--limit` supports bounded batches.

## Profile readiness

Readiness has two intentionally separate levels:

- A profile is **shadow-ready** after it has at least three reviewed members
  from three distinct recordings, no internal reviewed difference, no missing
  member, and no conflicting explicit attribution.
- A profile is **automatic-profile-ready** only when it is shadow-ready and its
  reviewed same-speaker graph is connected without a bridge edge. This requires
  redundant reviewed support rather than one transitive path.

Neither level means the whole system is approved for automatic mutation. The
acoustic model and decision policy have an independent promotion gate.
`profile-status` reports both counts. The existing blinded pair workflow can
prioritize missing internal support with:

```bash
pte identity review-next-speaker-pair \
  --selection-objective automation-readiness \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

That objective first nominates an unseen pair of observations already in the
same profile with at least three members. If no reinforcement pair remains, it
falls back to the existing profile-growth priorities. The listening packet and
human same/different decision are unchanged.

## Association decision

The matcher selects up to three eligible exemplars per shadow-ready profile,
preferring distinct source records and then distinct recordings. A candidate
profile must receive at least two `same_speaker` decisions, no
`different_speaker` decision, and no technical failure. Exactly one profile
must meet that rule. An explicit candidate name that conflicts with the
matched profile blocks the proposal.

Every candidate produces one of:

- `proposed_match`
- `no_match`
- `ambiguous`
- `conflicting_attribution`
- `insufficient_evidence`
- `analysis_failed`

Artifacts pin the observation and exemplar fingerprints, exact pair evidence,
model fingerprint, policy artifact hash and version, readiness state, outcome,
and complete result hash. They are written below ignored `shadow-runs/` paths
and are idempotent for the same inputs.

All artifacts explicitly set:

```json
{
  "shadow_mode": true,
  "registry_mutation_allowed": false,
  "automatic_assignment_allowed": false
}
```

The current default policy is an experimental development candidate. It is
accepted only for shadow measurement and cannot attach an observation.

Replay saved proposals against any human-reviewed registry state accumulated
later:

```bash
pte identity shadow-association-status \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

This reports confirmed, contradicted, and pending proposals, plus abstentions
that later received a reviewed profile. Precision is calculated only from
confirmed and contradicted proposals; pending cases are not silently treated as
correct. The replay is read-only.

## Promotion boundary

Shadow results must be evaluated against held-out human-reviewed associations
before registry mutation is implemented or enabled. Promotion requires both:

1. an automatic-profile-ready target; and
2. the independently promoted acoustic model and decision policy, including
   the required same/different counts, zero observed errors, variation
   coverage, frozen held-out evaluation, and no technical failures.

The next promotion increment must add a versioned machine-evidence ledger,
append-only reversible membership events, contradiction checks, and rollback.
A shadow proposal is never treated as a reviewed profile exemplar.
