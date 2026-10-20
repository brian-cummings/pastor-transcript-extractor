# Readable pastor profile: reader-first revision

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
`profile-v2.md` and `description-v2.json` provide the Markdown review and machine
record. V2 outputs live under `evaluation/pastor-profile-description-v2/`; V1 outputs and the original `--segment-view` artifact remain preserved.
The same description fingerprint is returned by check-only and generation; the
output directory additionally identifies the implementation/renderer manifest.

## Reader hierarchy and sample synthesis

The first screen answers what kind of preacher the sample suggests: a synthesized
assessment, a small at-a-glance table and understandable dimensions. Sermon titles
replace database IDs; a name supplied by source titles is explicitly unconfirmed.
Salvation findings are one theme table with named sermons or an exact count such
as “All 3 sermons,” rather than one repetitive paragraph per finding per sermon.
Descriptions lead to evidence explanations, then complete source passages. Raw
states, identifiers, probabilities, question versions, rules and implementation
remedies remain under closed **Technical details** disclosures.

`profile_presentation.py` is a downstream presentation module. It counts distinct
sermon membership in existing leading-topic summaries and approved local salvation
findings. This is sample synthesis, not a new topic cutoff, intensity score,
ministry recurrence claim or doctrinal adoption judgment. A missing theme stays
unknown; fewer findings never become evidence of doctrinal denial.

Four authored source-inspection descriptions in
`data/profile-presentation-source-reviews-v1.json` illustrate the existing treatment
meanings: biblical explanation, doctrinal reasoning, personal illustration and
practical application. Each description is bound to its complete passage by source
hash, text hash, timestamps and dimension. Changed or unreviewed sources do not
inherit the description. These are presentation inputs pending Brian’s acceptance,
not new model results, automatic admission rules or a frequency measurement. An
unreviewed maximum probability still cannot admit a style trait. The record and
manifest preserve the descriptions and their provenance.

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
python -m unittest discover -s tests -p 'test_profile_presentation.py'
python -m unittest discover -s tests -p 'test_segment_profile_view.py'
python -m unittest discover -s tests -p 'test_segment_cache_inventory.py'
```

These cover quoted/adopted non-inference, low versus missing values, unresolved
and routed states, changed contracts/eligibility, duplicate/overlapping sources,
counterevidence, immutable input behavior, escaping, internal navigation targets,
read-only cache probing, CLI isolation, distinct-sermon synthesis, stale source-review rejection, title/name boundaries and technical-term hiding in the initial and reader evidence views. Browser review additionally exercises
claim → source → claim links, disclosure opening and recording filters.

Brian’s bounded dataset acceptance command is the generation command above. Read
the rendered sample and approve/reject the concrete wording and withheld states;
no annotation file, new case selection or corpus evaluation is required.
