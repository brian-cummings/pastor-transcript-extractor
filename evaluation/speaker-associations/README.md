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
`profile-status` reports both counts. The existing exact-span pair workflow can
prioritize missing internal support with timestamped source-video links:

```bash
pte identity review-next-speaker-pair \
  --selection-objective automation-readiness \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

That objective first nominates an unseen pair of observations already in the
same profile when adding that edge would remove one or more bridge
dependencies from its reviewed graph. Profiles that are already bridge-free
are skipped. If no useful reinforcement pair remains, it falls back to the
existing profile-growth priorities. The listening packet and human
same/different decision are unchanged.

Current `proposed_match` artifacts also feed the blinded pair-review queue.
The selector chooses one exact same-band candidate/exemplar edge from the
multi-exemplar proposal, validates that the candidate remains unassigned and
the exemplar remains in the proposed profile, and applies normal history and
partition exclusions. The artifact is nomination provenance only: its acoustic
outcome is not shown in the listening packet and cannot create membership.

To refresh extraction and identity evidence in one content workflow, pass
`--identity` to `pte run`. Without that explicit flag, `pte run` does not launch
the corpus-wide acoustic stages.

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

Artifacts pin the observation and exemplar fingerprints, normalized-audio hashes,
exact pair evidence, reviewed-different constraints, model fingerprint, policy
artifact hash and version, profile membership, attribution and readiness state,
outcome, and complete result hash. The separately versioned input-fingerprint
contract ensures that a review or profile change creates a new immutable artifact
instead of colliding with an earlier run. Artifacts are written below ignored
`shadow-runs/` paths and are idempotent for the same inputs.

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

The `automation-readiness` pair-review objective excludes every observation
already attached to an `automatic_profile_ready` profile. Once a profile has
cleared its readiness blockers, that queue spends no further reviews growing or
reinforcing it; the separate `profile-growth` objective remains available for
intentional expansion.

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

## Machine-assignment boundary

Shadow results can flow into a versioned machine-evidence ledger. The default
checked-in `machine-assignment-human-on-loop-v1` policy permits bounded,
reversible activation only when `--apply-automatic` or
`--apply-machine-canary` is explicitly requested. Ledger rows are immutable
proposal evidence. A separate append-only lifecycle records activation,
revocation, or human confirmation, and active provisional assignments never
become reviewed profile membership or profile exemplars.

Every machine candidate must have a current accepted sermon observation, a
current automatic-profile-ready target, a unique multi-exemplar same-speaker
proposal, no different result or technical failure, no reviewed difference,
and no conflicting current attribution. Held-out fixture observations are
reserved from machine assignment. Reconciliation revokes stale observations,
including observations invalidated by a newer extraction or sermon
disposition.
Only association artifacts produced or deterministically reused by the current
identity invocation are considered; historical reports are never swept into the
ledger merely because they remain on disk.

Inspect the ledger without mutation:

```bash
pte identity machine-assignment-status \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

The status projection treats current reviewed membership as authoritative for
all machine evidence, including evidence that was never provisionally
activated. Reviewed matches appear confirmed, reviewed matches to another
profile appear revoked as contradictions, and neither remains in the activation
queue. Policy health counts use current deduplicated sermon/profile
associations rather than raw historical evidence rows.

Review the next pending or circuit-blocked machine proposal through the normal
blinded exact-span packet:

```bash
pte identity review-next-speaker-pair \
  --selection-objective automation-readiness \
  --reviewer REVIEWER_ID \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Machine-validation nominations are prioritized over ordinary association
confirmations. The machine outcome remains hidden and the approved human pair
judgment is still the only durable identity evidence.

Human-on-loop activation requires both:

1. an automatic-profile-ready target; and
2. the exactly pinned acoustic model and association policy, with unique
   multi-exemplar agreement and no contradictory or failed comparison.

This does not relabel the current acoustic candidate as a reviewed identity
authority. The output remains provisional, reversible, excluded from acoustic
exemplars, and subject to reconciliation and the policy circuit breaker.

A machine policy artifact must pin exact model and policy fingerprints, set a
hard maximum active-assignment count, and explicitly allow provisional
activation. The default is activated by `pte identity run --all
--apply-automatic`; the narrower `--apply-machine-canary` switch remains
available. Normal `pte identity run` and top-level `pte run --identity` record
evidence but do not activate it. Automatic-ready targets are withheld from the
ordinary blinded review queue. One reviewed contradiction trips the exact
policy fingerprint and revokes every remaining active assignment under it.
The trip also follows the implicated acoustic-model and association-policy
provenance across machine rollout-policy revisions; changing only a cap or
rollout artifact cannot silently reactivate the same contradicted decision
system. Any policy can also be rolled back explicitly:

```bash
pte identity rollback-machine-assignments \
  --policy-fingerprint SHA256 \
  --apply \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```
