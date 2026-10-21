# Readable pastor profile, evidence reuse and consequential gaps

The provider-free description workflow implements the bounded reuse increment in
[the product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) and
[the implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md).
The first screen presents the assessment and at-a-glance analysis; recording
comparison, supporting blocks, unknowns and transparent evidence follow.

Generate the existing profile 318 example from compatible saved evidence:

```bash
pte analysis structure-readiness --segment-view --description --json
```

Check source/membership/cache compatibility without writing outputs:

```bash
pte analysis structure-readiness --segment-view --description --check-only --json
```

Brian runs these bounded dataset commands. Codex runs focused unit tests and
prepares the inputs and interpretation. No provider, cache refill, new collection
or corpus evaluation is part of this workflow.

The generation command returns `index.html` under the configured application base.
V5 companions are `profile-v5.md`, `description-v5.json`, `review-v5.json` and
`next-capability-v2.md/json`. The latter is the current consequential-gap review,
not another request to run the completed assurance pilot. V5 outputs live under
`evaluation/pastor-profile-description-v5/`; earlier versions, including V4, remain preserved.
Check-only and generation return the same description fingerprint. The output
directory additionally identifies the implementation/renderer manifest.

## Concrete descriptions and local accounts

V5 assembles explanations from the existing reviewed style descriptions and local
binding proposals. It does not summarize full transcripts again or infer a
position from a topic/probability. Explanatory points retain clause-level links,
source compatibility, speaker/use/scope, qualifications, unknowns and proposal status.
Incompatible or missing reviewed inputs are withheld without replacing them with
nearby text. With fewer or no reviewed inputs, the narrower existing view remains.

The assessment uses concrete reviewed explanations. The at-a-glance uses concise
authored descriptors linked to those accounts; recording navigation groups the
fuller accounts by their actual source recording. Reviewed local proposals are
visible in the main reading path. Separate examples do not establish a connected
argument, complete sermon summary or dominant preaching method. General limits
are consolidated while meaning-changing qualifications stay with the reading.

The four reviewed explanations retain their original text and source identity.
`data/profile-presentation-source-reviews-v2.json` adds concise presentation
descriptors; V1 remains unchanged. The manifest pins that input and the explanatory
assembly helper. Descriptor counts are not an acceptance target.

The CLI receipt and review JSON explicitly keep reader acceptance pending. Brian generated V5 on 2026-10-21, and Codex verified the saved artifacts and
inspected the actual wording. Concrete wording acceptance remains pending; the
revision’s reader usefulness is not inferred from successful generation.

## Evidence integration

The existing loader checks source membership, source hashes, eligibility,
question/model/policy identity and nonoverlapping block geometry. Existing topic,
treatment and local salvation observations keep their original meanings.
Read-only reuse checks inspect registered full-pack, individual-leaf/refinement
and saved composed-answer identities separately. They never call assessment,
hydration, migration, composition or refill APIs that could infer or write caches.
A full-pack miss is not proof that individual compatible answers are absent.

Compatible additional raw judgments remain explicitly unadmitted where there is
no approved descriptive/admission rule. A saved probability cannot silently
become an adopted position, personal trait or listener circumstance. Source-reviewed
proposals retain their proposed status. Unchecked artifact families are distinguished
from inspected absent or incompatible results.

Each underlying claim records the observation supply used to support it. Each
consequential gap records the missing distinction, inspected reuse outcomes,
responsible upstream owner, smallest remedy, acceptance check and applicable hold.
Compatibility is never relaxed simply to fill a profile section.

## Aggregation and examples

Recording-level evidence is assembled before sample patterns. The reader can see
where a topic appears in existing leading-topic summaries and where a local
salvation relationship is observed, below threshold, unrouted or missing. These
are descriptions of stored evidence in the selected recordings. They do not
establish independent recurrence, frequency, prevalence, chronology or ministry
stability. Known repeated references do not multiply support.

Source-reviewed style descriptions retain exact source/text hashes, timestamps
and dimension. Changed sources do not inherit the description. An unreviewed
maximum treatment probability remains an inspection candidate, not an admitted
style trait. Topic attention does not establish agreement, and coexisting themes
are not automatically doctrinal opposition.

Supporting examples begin with an established point and its eligible support set.
The selector preserves point/rule IDs, supporting observations, recording scope,
complete selected blocks, source provenance and counterevidence. It does not
search the whole transcript for a new theological claim or classify support/refutation.
The block illustrates the finding; it cannot establish how often an approach occurs.
Optional excerpt extraction remains held. Removing an example must not change the
analytical conclusion.

## Scope and review

The sample remains profile 318’s three selected development recordings,
4589 / 281 / 3973. The baseline has 158 eligible topic/treatment blocks and
33 routed salvation blocks. The builder remains generic over the reviewed
inventory; it does not select a larger collection.

The descriptive rules are explicit, versioned proposals for human review; they
are not measurement ground truth. Unmeasured, unrouted, incompatible,
below-threshold and unresolved evidence remain distinct. Missing support is not
opposition or denial. Benchmark comparison and accepted identity remain unavailable
where their required inputs are absent.

A consequential semantic gap goes to the affected category-leaf producer or
existing shared upstream binding component. Aggregation and quotation selection
cannot supply a missing target, speaker, adoption decision or attached qualification.
The earlier TypeSafe and connected-extraction failures remain historical results;
this workflow does not automatically start another variant.

New provider/model calls, broader collection, changed measurements/admission,
production activation, scoring/ranking/comparison, ministry-wide stability and
Ollama quotation execution remain held.

## Focused verification

```bash
python -m unittest discover -s tests -p 'test_profile_*.py'
pte analysis structure-readiness --segment-plan --json
```

The tests use small prepared inputs and cover compatibility rejection, read-only
reuse, conservative aggregation, point/block support, provenance, missingness,
escaping and internal navigation. They do not substitute for Brian’s dataset review.

Brian’s acceptance step is to run the generation command, open the returned HTML,
and review the assessment, recording variation, source support and withheld
conclusions. Codex owns interpretation and any concrete follow-up proposal.
No annotation files, new case selection or JSON authoring are required.
