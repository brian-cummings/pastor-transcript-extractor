# Source-reviewed theological proposition-binding pilot

**Subsequent implementation:** [reusable proposition binding separated from assurance](PROFILE_PROPOSITION_BINDING.md) now represents these same ten readings through the new architecture. Use `pte analysis profile-proposition-review --json` for the current review. This document and the original pilot remain the preserved baseline.

**2026-10-20: executed; concrete proposed readings await Brian’s review.** Brian
explicitly authorized the three prepared passages. Assurance is the test domain,
not the capability or a pastor-wide classification target. No additional planning,
readiness, provider or authorization gate precedes these completed readings.

Reproduce the results:

```bash
pte analysis profile-binding-review --json
```

The command writes `index.html`, `readings-v1.md` and `readings-v1.json` under the
configured application base directory in `evaluation/profile-binding-source-review-v1/`.
For source/coordinate freshness without artifact writes:

```bash
pte analysis profile-binding-review --check-only --json
```

## Concrete deliverable

The three passages yield ten distinct proposed source readings:

- **Demons & Dry Places, 38:00–39:00:** the invited mercy-versus-works prayer and
  the preacher’s explicit gospel endorsement; the declaration that God faithfully
  completes the work begun until the day of Jesus Christ. Neither automatically
  becomes permanent security or a retention predicate.
- **The Shaking, 45:20–47:52:** Jesus’ saving desire in the preacher’s own voice;
  Paul’s reported self-description; Jesus’ attributed warning with its stated
  ground; the reported “middle of the road” identity; and the preacher’s own
  criticism of that stance. Criticism is not a manufactured logical opposite or
  an assertion that the reported people are not Christians.
- **The American Experiment, 98:42–99:21:** the preacher’s rhetorical invitation,
  the prospective listener’s forgiveness declaration, and the invited statement
  about a prepared place in heaven. Encouraging these words is not an attested
  listener assertion, evidence of pastoral uncertainty, or a settled claim of
  permanent security.

Each reading provides the actual proposition paraphrase, exact claim span, authored
G1 field choices, all eleven field reviews, exact supporting text/character offsets,
withheld conclusions and linked contract gaps. Complete targets, existing context,
source hashes, timestamps and original context diagnostics accompany the readings.
These are Codex-authored source-reviewed proposals, not model outputs or independent
human semantic validation. Brian reviews concrete results, not an annotation task.

## Existing representation, unchanged

`profile_binding_pilot.py` validates authored literal spans and serializes explicit
source-reviewed decisions through the existing pure G1 `compose` function. It does
not call candidate discovery, construct a provider, ask new questions or infer field
choices. Existing subject/relation/voice/adoption/expression values are enforced.
The contract and composer are hash-pinned. No enum, predicate, condition kind,
threshold or production admission rule is changed.

The source-review narrative is deliberately separated from the formal G1 encoding.
A `no_in_scope_claim` or `binding_withheld` state does not erase a concrete theological
assertion whose meaning falls outside the frozen proof vocabulary. Known voice and
adoption facts remain available even where the formal relation is withheld. All
original observations and profile claims remain unchanged; no bindings are projected
into the pastor profile.

## Recommendation from the completed readings

**G1 is a useful backbone, but not sufficient unchanged for the general capability.**
The envelope preserves exact source content, separates voice/adoption/polarity and
supports conservative partial records. The source readings expose these precise
limits without extending the contract:

1. The finite assurance/ramp proof predicates cannot faithfully represent every
   concrete theological proposition in the supplied passages.
2. The proof voice/expression menus do not distinguish an invited or prospective
   utterance from an actual report/assertion event.
3. Concession (“anyway”) and stated rationale (“because ...”) can be retained in
   evidence, but are not typed by a condition/exception list. Do not invent an
   if/only-if salvation condition.
4. A negative evaluation must identify its exact target before adoption/polarity
   can be normalized; disapproval of neutrality does not deny Christian identity.
5. Question form alone does not separate invitation from information-seeking and
   cannot manufacture unsettled belief or expressed uncertainty.

The exact readings supporting each gap are linked in the report. These are not five missing schema fields or five requests for new measurements: predicate/menu scope is distinguished from structured representation limits. Evaluation targeting and conservative question handling already follow G1 discipline; literal binding evidence retains information even when the proof menus cannot type it. The smallest
future design review should separate the reusable binding envelope from domain
predicates and examine speech-frame/qualification needs, reusing applicable G2/G3
contracts first. This pilot implements none of those extensions and makes no claim
about automatic binding reliability or generalization to other theological subjects.
The three supplied readings also do not validate positive condition/exception
binding to an admitted assurance predicate or explicit speaker uncertainty.

## Focused verification

```bash
python -m unittest discover -s tests -p 'test_profile_binding_pilot.py'
```

Tests cover existing G1 control serialization, literal source integrity,
context-only exclusions, unknown/partial fields, frozen vocabulary, unbound
conditions, source/membership/context freshness, escaping/link targets, read-only
CLI behavior and absence of provider execution or profile projection. Structural
checks do not decide whether the authored semantic interpretations are correct.

The older `next-capability-v1` packet remains the historical preparation artifact.
The current result is this executed pilot and its three concrete source reviews;
no new approval is required to generate or inspect them. Providers, measurements,
automatic binding, new doctrine vocabulary, collection, collector/threshold changes,
discovery, comparison/profile projection and Ollama execution remain held.
