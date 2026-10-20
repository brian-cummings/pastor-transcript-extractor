# Source-reviewed theological propositions, independent of assurance predicates

**2026-10-20: implemented; ten concrete proposed readings ready for Brian’s review.**
The reusable binding layer now preserves the source proposition even when the optional
assurance interpretation is a non-match or unresolved. This implements the bounded
architectural separation authorized after the [completed pilot](PROFILE_BINDING_SOURCE_REVIEW.md).
It does not activate automatic binding or populate pastor-wide theological positions.

```bash
pte analysis profile-proposition-review --json
```

This writes `index.html`, `readings-v1.md` and `readings-v1.json` beneath the configured
application base directory in `evaluation/profile-proposition-source-review-v1/`.
The command prints the immutable output path. For source/literal verification without
artifact writes:

```bash
pte analysis profile-proposition-review --check-only --json
```

The current packet is `712681d5d32d7b4562642e8b1f3d6ab6a75c7bcb9b12162cf46a337dafc863fd`;
its report fingerprint is `dfe49260d2cc0298d67cafb112a9c40bb72e12d19ee52009a0aa72abd6b45fed`.
Open `index.html` for the readable summary, ten-row glance table, evidence disclosures,
unknowns, separate assurance interpretations and consequential limitations. Markdown
and JSON contain the complete records and reviewed mappings.

## What changed

- `theological_binding.bind(texts, authored, provenance)` compiles a source-reviewed
  proposition independently of subject/relation vocabularies. It preserves exact
  claim text, readable meaning, voice, preacher adoption, polarity, surface expression,
  conditions/exceptions, qualifications, scope, expressed uncertainty and source identity.
- `binding_evidence.py` shares the original literal-coordinate checks with the old
  pilot. The original G1 contract/composer and original curated readings are unchanged.
- `assurance_binding_adapter.interpret(binding, texts, reviewed_interpretation)` requires
  an explicit mapping to the **same exact bound proposition**, then uses the unchanged
  G1 serializer and original reviewed predicate decisions. Generic adoption/polarity
  is not silently copied into a narrower normalized predicate. All ten resulting G1
  records equal the preserved pre-separation artifact.
- `profile_proposition_review.py` and the new curated source-review supplement demonstrate
  the same ten readings through both layers. The loader reuses the completed pilot’s
  source/membership checks, supplied windows, hashes and context truncation diagnostics.
  It performs no discovery, new provider inference or database writes.

## Reuse and the one necessary speech-frame distinction

G1 supplies exact evidence/provenance, independent voice/adoption, condition/exception,
scope and expressed uncertainty. G2 supplies evidence-node roles and development links:
Paul’s honesty example uses `reason_supports_claim`; the lukewarm warning retains its
stated reason; the neutrality critique `addresses_alternative`. Both relation endpoints
and the relation evidence must be target-grounded. These are authored source reviews,
not new automatic G2 measurements or production admission.

The saving-desire “anyway” is a G2 `qualification` node explicitly attached to the
proposition with a reviewed explanation. It is not a new condition kind, nor a broadened
`qualifies_claim` relation. The literal contrast and its meaning remain inspectable
without inventing a concession ontology.

G3’s invitation/address and addressee distinctions link the preacher’s question to
its offered listener response. Act-level `own_or_adopted` belongs to the invitation;
it does not certify proposition-level adoption, actual listener uptake or circumstance
binding. No G3 admission rule or posture measurement is applied.

Utterance occurrence (`actual`, `projected`, `unresolved`) is the small additional
orthogonal distinction. An embedded declaration can have assertion form and a projected
listener voice while the outer current-preacher question is an invitation. `actual`
means presented as spoken in the sermon/report, not independent historical verification;
the screen labels reported material as **reported speech**.

## The ten readings and conservative interpretation

The two **Demons & Dry Places** readings retain the mercy-versus-works prayer with its
explicit gospel endorsement, and God’s faithful completion of a good work with its
time scope. Neither is forced into a permanent-security or retention predicate.

The five **The Shaking** readings preserve saving desire despite known works, Paul’s
reported confession, Jesus’ attributed warning, reported middle-road identity and the
preacher’s separate criticism. Surrounding injunction/gloss and affirmative application
support the local adoption/use of Paul’s example and Jesus’ warning without requiring
“I agree.” Quotation alone does not support adoption. A literal ranking of sinners,
a particular loss mechanism and denial of the reported people’s Christian identity
remain withheld. The old G1 records remain visible as separately reviewed narrower
interpretations; they are not equivalent to the richer generic use findings.

The three **The American Experiment** readings separate the actual invitation from
projected forgiveness/place-in-heaven declarations. The preacher affirmatively offers
those declarations as confidence language; no actual listener speech, saving standing,
unconditional guarantee or expressed theological uncertainty is inferred.

## Verification and limits

**70 focused tests pass**: 9 generic/adapter, 8 new review, 10 original pilot, 40 existing
profile/evidence and 3 plan/CLI checks. The new controls cover arbitrary non-assurance
theology, source drift/context leakage, quotation-only versus discourse adoption,
projected speech, questions, conditional retention, rejection without an opposite,
unsupported uncertainty, relation endpoints, source/mapping identity, rendering and CLI
write isolation. These are structural/regression checks, not independent semantic validation.

Live verification checked every literal span in the ten records, compared all ten
G1 records against the preserved pre-separation artifact, and compared the unchanged
profile against its preserved V3 artifact. Check-only ran with provider construction
and file writes blocked. Browser checks verified ten summary rows, reported/projected
labels, closed technical disclosures, zero broken internal links, evidence-to-full-target
navigation and return links, adoption rationale and the projected forgiveness reading.

The consequential limitations and smallest remedies are also in the packet:

- Source interpretations remain proposed; automatic accuracy, discovery recall and
  general theological coverage are unestablished. Brian reviews concrete results.
- No positive bound salvation condition/exception or explicit theological uncertainty
  occurs in these ten cases. Authored controls exercise serialization, not detection.
  Empty conditions and `not_stated` must not become unconditional doctrine or certainty.
- Concessions have exact attachments and reviewed explanations, not a queryable causal
  ontology. Introduce further semantics only for a separately justified use.
- External quotation accuracy, actual hearer identities/uptake, production admission
  and pastor-wide tendencies remain unknown. Narrow assurance mappings retain their
  own unresolved/non-match states.

No providers, new measurements, collection, automatic binding/discovery, profile-wide
projection, comparison/scoring or Ollama quotation execution occurred. The original
profile and pilot remain reproducible. The next human action is to review this concrete
packet; Codex owns interpretation of feedback and recommendations.
