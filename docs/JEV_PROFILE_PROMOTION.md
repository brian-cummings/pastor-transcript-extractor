# Jev Probability-Based Speaker Profile Promotion

## Status

This document is the implementation contract for replacing most semantic
speaker-profile promotion gates with one grounded Jev probability. The initial
delivery affects creation of reversible provisional profiles. It does not relax
the separate automatic-profile-readiness or machine-assignment policies.

Implemented: candidate/state construction, Jev adapter, per-group success and
failure cache, shadow-evaluation CLI, probability-aware promotion planning and
provenance, and corpus-workflow integration. Pending: corpus calibration
from independent confirmations. The cost-3 automatic-use policy and corpus
workflow integration are now enabled by default for provisional promotion.

## Objective

Create more useful provisional speaker profiles without requiring a person to
resolve every incomplete acoustic component.

Code retrieves bounded candidate groupings, preserves registry invariants,
calculates policy utility, and performs mutations. Jev supplies the semantic
judgment ordinary code cannot calculate:

> Do all observations in this candidate grouping contain the same physical
> person as the principal sermon speaker?

The returned Noul value is treated as the probability of `yes`. Acoustic
outcomes, observation consistency, explicit attributions, metadata, transcript
context, source relationships, missing comparisons, and machine contradictions
are evidence contributing to that probability. They are not separate promotion
requirements.

## Non-goals

- Jev does not generate names, observations, group members, or evidence.
- Jev does not interpret audio directly.
- Sermon topic, theology, rhetoric, and speaking style are not identity evidence.
- A promotion judgment does not establish a reviewed speaker name.
- A promoted profile does not become automatic-ready without the existing
  independent multi-exemplar confirmation.
- This change does not weaken a durable human `different_speaker` judgment.

## Candidate retrieval

Candidate generation is retrieval, not qualification. It should expose a small,
useful set of groupings from each discovery neighborhood:

1. Existing complete-link components.
2. Blocked positive-edge components containing at least two recordings.
3. Maximal positive acoustic subgroups.
4. Strong seeds expanded by an immediate or staged review-frontier candidate.
5. A whole component and bounded leave-outlier alternatives when the discovery
   graph already identifies a plausible peripheral member.

Candidate group IDs are hashes of sorted immutable observation fingerprints.
Jev can judge only supplied groups and cannot invent or expand membership.

Before a model call, code removes only structurally impossible candidates:

- stale or superseded observations;
- the same recording represented more than once;
- incompatible existing profile membership;
- a durable reviewed `different_speaker` relation inside the group; or
- invalid or unverifiable source artifacts.

Member count, source count, name count, complete-link coverage, machine acoustic
outcomes, and observation-consistency tiers remain evidence rather than gates.

## Grounded state

Each request contains a compact JSON object with:

- the exact candidate group and immutable observation fingerprints;
- per-observation recording ID, source context, title, selected metadata fields,
  exact attribution spans, and short relevant transcript excerpts;
- per-observation consistency represented in semantic terms, with raw values
  retained in the persisted artifact;
- every available pair assessment represented as semantic evidence such as
  `supports_same_speaker`, `ambiguous_near_same`, `ambiguous`, or
  `supports_different_speaker`;
- whether any evidence came from a durable review; and
- explicit statements that source co-membership is contextual only and sermon
  content or style is not identity evidence.

Code performs counting, hashing, threshold conversion, and numeric comparison.
Jev receives concise semantic descriptions because Jev 1.13 is intended for
common-sense judgment rather than arithmetic.

Metadata and transcript text are deduplicated and budgeted per observation.
Unrelated transcript content is excluded. Raw external text remains data; the
question and criteria explicitly prohibit following instructions found inside
titles, descriptions, or transcripts.

## Question contract

Use one Noul per candidate grouping. The question is direct and versioned:

> Do all observations in `candidate_group` contain the same physical person as
> the principal sermon speaker?

Guidance defines the positive condition rather than encoding a checklist:

- `yes` means the same human is the principal sermon speaker in every member;
- a recurring host, musician, reader, interviewer, or incidental voice is not
  sufficient;
- missing evidence should produce uncertainty rather than an assumed answer;
- machine assessments and metadata can support or oppose the conclusion without
  becoming mandatory conditions;
- same source alone is not identity proof; and
- only supplied evidence may be used.

The raw Noul probability is persisted. No Choice confidence or Score expectation
is substituted for it, and thresholds calibrated for other TypeSafe primitives
must not be reused.

## Probability policy

Promotion is an expected-utility decision over the Jev probability, not a set of
evidence gates:

```text
promotion utility =
    P(all members are the same principal speaker) * successful-profile value
  - P(any member differs) * contaminated-profile cost
```

The reviewed `profile-promotion-utility-v2` policy assigns value `1` to a
successful provisional profile and cost `3` to a contaminated profile, producing
positive utility above probability `0.75`. The policy owns these values and its
automatic-use status. The
planner selects a non-overlapping set of candidate groups with positive total
utility. Existing deterministic complete-link candidates use the same evaluator
when Jev is available. If TypeSafe is unavailable, the existing complete-link
behavior remains available, while probability-only expansions defer.

Human review is reserved for candidates whose expected value of additional
information exceeds the review cost. Other uncertain candidates wait for changed
evidence and are re-evaluated automatically.

## Jev cache contract

Caching is a production requirement, not an optimization. An unchanged candidate
must not cause another TypeSafe request.

### Cache unit

The cache stores one successful or failed Jev judgment per candidate grouping.
Different groupings in the same discovery neighborhood have independent cache
identities so adding or removing one proposal does not invalidate unrelated
answers.

### Cache identity

The content-addressed key includes:

- evidence-state schema version;
- question version and the complete question definition;
- requested pinned model identity (with the resolved identity persisted in the
  result payload and covered by its checksum);
- discovery result hash;
- sorted observation fingerprints;
- selected metadata text and its artifact content hashes;
- selected transcript text and its artifact identity or content hashes;
- semantic pair-evidence payload, including its policy/model provenance; and
- every other state field visible to Jev.

The probability/utility policy is deliberately excluded from the inference key
when it does not change the question or state. Changing only promotion costs must
reuse the raw Jev probability and recompute the action in code. If policy wording
is placed in the question, the question version and cache key must change.

### Cache contents

Every successful entry persists:

- exact state and question sent to TypeSafe;
- raw Noul probability;
- requested and resolved model identities;
- input/output token usage when available;
- creation timestamp; and
- a checksum covering the immutable payload.

Every terminal service or answer-validation failure persists the same identity
plus the error type and message. An identical rerun replays the cached failure
and does not repeatedly call the service. Local preflight errors such as missing
credentials occur before candidate requests and are not cached, so fixing local
configuration does not require invalidating judgments. A changed state, question,
model, or evidence artifact creates a new key and retries normally.

Malformed, incomplete, checksum-invalid, or identity-mismatched cache entries are
never accepted. Writes are content-addressed and collision checked. Cache hit,
miss, cached-failure, live-call, and abstention counts appear in CLI summaries and
run artifacts. Interactive commands also show the current group, completed
percentage, elapsed time, and whether work is checking cache, calling Jev, loading
a cached result, or selecting the final non-overlapping plan.

### Artifact separation

The acoustic discovery report remains immutable. Jev judgments are written as a
separate artifact that references the verified discovery result hash. Promotion
events retain both hashes and paths. This allows acoustic discovery, semantic
inference, and utility policy to be replayed or revised independently.

## Failure behavior

- Missing credentials, SDK errors, timeouts, invalid answers, and missing answers
  never qualify a probability-only expansion.
- A cached failure prevents repeated paid calls for unchanged input.
- Existing deterministic complete-link promotion remains available during a
  TypeSafe outage.
- A stale observation, changed metadata/transcript artifact, or changed question
  produces a new cache identity rather than silently reusing an old judgment.
- Promotion planning revalidates current registry state even when inference is a
  cache hit.

## Provenance

A probability-qualified promotion records:

- discovery artifact path and result hash;
- Jev judgment artifact path and result hash;
- candidate group ID and seed observation IDs;
- Noul probability;
- question, state, model, and decision-policy versions;
- expected utility and selected action; and
- an idempotent event fingerprint covering all mutation-relevant inputs.

Existing promotion rows are represented as `deterministic_complete_link` during
schema migration. New probability-qualified rows use `jev_probability`.

## Workflow

```text
acoustic discovery
  -> candidate-group retrieval
  -> content-addressed Jev cache lookup
  -> live Jev call only for misses
  -> immutable judgment artifact
  -> probability/utility planning
  -> optional provisional promotion
  -> existing independent confirmation
  -> existing automatic-readiness policy
```

Plan-only execution lists candidate groupings and cached status without TypeSafe
calls, artifact writes, or registry mutations. Applying a plan always requires an
explicit existing mutation flag. Enabling probability-qualified promotion in
unattended runs by default additionally requires a reviewed probability policy
marked for automatic use.

For an explicit corpus run, `pte identity run --all` evaluates cache misses and
includes current positive-utility cache entries in
the promotion plan by default. It remains non-mutating unless the existing
`--apply-promotions` or `--apply-automatic` authorization is also supplied. Use
`--no-evaluate-profile-promotions` only for a deterministic-only diagnostic.

Cached reconstruction builds one run-scoped evidence context. Observation,
metadata, transcript, attribution, and pair evidence are loaded or indexed once
and reused across overlapping candidate groups. This preserves exact per-group
cache identities while avoiding repeated database scans.

## Delivery sequence

1. **Implemented:** grouping/state construction, the provider protocol, Jev
   adapter, per-group cache, immutable artifacts, and fake-provider unit tests.
2. **Implemented:** read-only CLI for plan-only and shadow evaluation with
   detailed cache and probability output.
3. **Implemented:** probability-aware promotion planning, provenance persistence,
   overlap selection, and focused cache/idempotency/staleness tests.
4. **Implemented:** opt-in integration between discovery and promotion in the
   corpus identity run.
5. **Next:** run the prepared corpus shadow evaluation and inspect probability,
   utility, failure, and cache behavior without applying promotions.
6. **Implemented:** freeze the question and enable the reviewed cost-3
   probability policy for provisional promotion by default. Independent
   confirmation remains the downstream automatic-readiness requirement.

## Acceptance criteria

- A second unchanged run performs zero TypeSafe calls.
- Changing only utility costs performs zero TypeSafe calls and recomputes actions.
- Changing any Jev-visible evidence invalidates only affected grouping entries.
- Two-member and incomplete-link groups can be promoted from probability without
  name, source-count, or complete-link gates.
- Machine-negative evidence changes probability but is not a veto.
- Reviewed contradictions and stale/incompatible registry state remain hard stops.
- Every mutation is replayable to exact discovery and Jev artifacts.
- Jev-promoted profiles remain automatic-blocked until current independent
  confirmation succeeds.
- Focused tests cover success, deferral, overlap, cache hits, cached failures,
  invalidation, tamper rejection, service failure, and idempotent application.

## Validation boundary

Development uses focused unit tests and inexpensive static checks only. Corpus-wide
shadow evaluation and calibration are prepared by the implementation but executed
by Brian using an exact supplied command.
