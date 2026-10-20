# Readable pastor profile: first implementation

The provider-free description workflow implements milestones 1–3 of the active
[product](PASTOR_PROFILE_PRODUCT_PLAN.md) and
[implementation](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) plans. The consequential
gap map is part of the generated profile, not another prerequisite planning gate.

Generate the reviewed profile 318 example using existing evidence:

```bash
pte analysis structure-readiness --segment-view --description --json
```

Check current source/membership/cache compatibility without writing outputs:

```bash
pte analysis structure-readiness --segment-view --description --check-only --json
```

The command prints the generated `index.html` path under the configured application
base directory. Open it to review the assessment, at-a-glance table, dimensional
analysis, claim ledger, consequential gaps and full source windows. Companion
`profile-v1.md` and `description-v1.json` provide the Markdown review and machine
record. The original `--segment-view` artifact and renderer remain reproducible.
The same description fingerprint is returned by check-only and generation; the
output directory additionally identifies the implementation/renderer manifest.

## Interpretation boundaries

`profile_description.py` assembles existing compatible observations after the
original loader checks inventory integrity, reviewed membership, source hashes
and ownership/eligibility. It rechecks question/model/policy and target identity,
source projection membership and nonoverlapping segment geometry.

- Topics: reuse the inventory’s existing four highest per-recording attention
  summaries. Each clause links to representative windows, all underlying local
  topic scores and the summary’s stored counterevidence. No pastor average,
  cutoff, belief, agreement or priority is derived.
- Treatment: retain all local probabilities; select one maximum per dimension
  per recording for **inspection only** (ties: earliest time, then block ID).
  Selection never admits a style trait. Lower values remain measured values,
  not missing evidence. The four dimensions keep their existing meanings.
- Salvation: use only the nine approved leaves and frozen local observation
  thresholds. Preserve all measured values and separately disclose unrouted,
  missing-compatible-result, below-threshold and unresolved states. A local
  observation never establishes adoption, polarity or doctrinal denial.
- Coverage: source and membership identities participate in the derived record.
  The selected development recordings do not establish independent recurrence
  or stable ministry tendencies. Source safety is inherited from the original
  read-only gate; this feature does not perform a new audit of every judgment.

The wording rules are versioned, proposed descriptive interpretations for review.
They do not revise measurement admission, thresholds or raw receipts. The worked
example is not a fixture whose desired prose future inference should reproduce.
The builder is generic over the reviewed inventory; the existing loader selects
the pinned development sample, not a newly chosen collection.

## Reuse and gap review

Generation/check-only also perform read-only exact-current Scripture-run lookups
for the selected recordings. They do not execute reference detection or alignment.
Registered leaf-pack cache identities, including historical refinements and any
composed answers at those identities, are checked using pure identity/path helpers
and file reads. No `assess`, migration, hydration, composition, cache refill or
provider is invoked. Missing exact paths do not establish global cache absence.

The prioritized gap map records withheld wording, precise cause, reader impact,
reuse options, smallest remedy and whether work is code, interpretation, semantics,
sampling, metadata or comparison validation. Reuse-check results accompany it.
New provider/model calls, collection, new semantic measurements, profile scoring,
comparison/ranking, production activation and Ollama execution remain held.

## Focused verification

```bash
python -m unittest discover -s tests -p 'test_profile_description.py'
python -m unittest discover -s tests -p 'test_segment_profile_view.py'
python -m unittest discover -s tests -p 'test_segment_cache_inventory.py'
```

These cover quoted/adopted non-inference, low versus missing values, unresolved
and routed states, changed contracts/eligibility, duplicate/overlapping sources,
counterevidence, immutable input behavior, escaping, internal navigation targets,
read-only cache probing, and CLI isolation. Browser review additionally exercises
claim → source → claim links, disclosure opening and recording filters.

Brian’s bounded dataset acceptance command is the generation command above. Read
the rendered sample and approve/reject the concrete wording and withheld states;
no annotation file, new case selection or corpus evaluation is required.
