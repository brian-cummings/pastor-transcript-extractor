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

Shadow results can now flow into a versioned machine-evidence ledger, but the
checked-in `machine-assignment-shadow-v1` policy cannot activate assignments.
Ledger rows are immutable proposal evidence. A separate append-only lifecycle
records activation, revocation, or human confirmation, and active provisional
assignments never become reviewed profile membership or profile exemplars.

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

Promotion to a canary policy still requires both:

1. an automatic-profile-ready target; and
2. an independently promoted acoustic model and decision policy, including
   the required same/different counts, zero observed errors, variation
   coverage, frozen held-out evaluation, and no technical failures.

A canary policy artifact must pin those exact model and policy fingerprints,
set a hard maximum active-assignment count, and explicitly allow provisional
activation. Activation also requires `pte identity run --all
--apply-machine-canary --machine-assignment-policy POLICY.json`; neither normal
`pte identity run` nor top-level `pte run --identity` activates it. The existing
blinded review queue prioritizes active canaries. One reviewed contradiction
trips the exact policy fingerprint and revokes every remaining active assignment
under it. Any policy can also be rolled back explicitly:

```bash
pte identity rollback-machine-assignments \
  --policy-fingerprint SHA256 \
  --apply \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```
