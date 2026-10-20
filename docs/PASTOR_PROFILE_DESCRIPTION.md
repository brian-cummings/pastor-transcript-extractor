# Readable pastor profile and next-capability decision

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
`profile-v3.md` and `description-v3.json` provide the Markdown review and machine
record. V3 outputs live under `evaluation/pastor-profile-description-v3/`; V1/V2 outputs and the original `--segment-view` artifact remain preserved.
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

## Next capability: qualified theological positions

Brian’s feedback recognizes the product-language pass as successful. The next
increment therefore makes only small presentation fixes: at-a-glance style terms
are terse, “A closer look” supplies examples instead of repeating the assessment,
and the faith theme reads “salvation received through faith.”

The same CLI now also writes `next-capability-v1.md` and `next-capability-v1.json`
with a concrete recommendation: distinguish the preacher’s own theological
assertions from explanation, quotation or rejection, retaining conditions and
scope. The profile links to the proposal under “What would most improve this
assessment?” This is a prepared decision packet, not a new measurement workflow.

The recommended first slice is assurance: knowing present acceptance, possible
loss and retention. It reuses the bounded G1 representation rather than expanding
salvation meanings or introducing a doctrine catalog. Three exact-source passages
are prepared, including an existing below-threshold contrast. Their full texts,
source hashes, timestamps, current states, questions and non-inference boundaries
are supplied. No position is populated. Stale cases are excluded without selecting
replacements or relaxing a threshold.

The packet checks the existing closed G1 feasibility decision and its actual input,
not the older design-only wording. Fixed-passage PASS does not establish discovery
or sample completeness. The exact prepared targets do not match that historical
pilot; this is neither a global cache census nor proof that no compatible answer
could exist elsewhere. G1 discovery HOLD, source-only V3 limitations and A1’s
bounded G3 scope are preserved. No closed pilot is rerun.

**Pilot now executed:** Brian authorized source-reviewed theological proposition binding on the prepared passages. Assurance is only the test domain. Generate the three concrete passage reviews, ten proposed readings and exact field evidence with:

```bash
pte analysis profile-binding-review --json
```

Read [the completed pilot](PROFILE_BINDING_SOURCE_REVIEW.md) for the source readings, G1 fit/gaps and test scope. The older next-capability files are historical preparation, not a current request for another authorization. No proposed bindings are projected into the profile. Codex owns revisions; Brian reviews concrete results rather than annotating sources or authoring JSON.

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
python -m unittest discover -s tests -p 'test_profile_capability_review.py'
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
