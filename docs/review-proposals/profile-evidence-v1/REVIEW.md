# Shared evidence and provider-free consumer packet V1

Status: **prepared design for review, 2026-10-14**. The authorized work is the shared contract, proposed estimands and prepared consumer expectations. This packet implements no production consumer, provider integration, collection, pastor projection/comparison or scores. G1 implementation/expansion stays held; G2/G3 construct feasibility stays closed; G4 stays deferred.

The recommendation is to retain the C01–C20 product specification and adopt an evidence-first partial view: show what an eligible passage supports, show the stronger field it cannot yet establish, and retain the reason. A profile need not wait for every capability to become useful. It must not turn examples into a recurring pastor characterization or conceal missing positions, development or address.

## Review artifacts

- [CONTRACT.md](CONTRACT.md): normative source, provenance, compatibility, independence, field and missingness rules.
- [FIELD_CATALOG.md](FIELD_CATALOG.md): all 20 desired characteristics, target statements, compatible inputs and missing information. D01–D06 remain held.
- [ESTIMANDS.md](ESTIMANDS.md): seven distinct targets and their denominator/activation requirements.
- [CASES.md](CASES.md): 17 prepared cases with exact expected visible wording; includes useful partial fields and known frozen withholdings.
- [packet-v1.json](packet-v1.json): complete machine-readable inputs and expected views, including evidence links, unknowns and source hashes.
- [schema-v1.json](schema-v1.json), authored by [contract.py](contract.py): closed wire schema for this example-level packet. The schema deliberately cannot serialize non-null rates, recurrent characterizations, comparisons or scores. Later production adapters and higher claim levels require another contract revision/decision.

There are eight distinct frozen provider rows (two G2; six G3), with one G2 row reused in the two-panel illustration. Seven were originally authored passages; the eighth is a natural, source-linked busy-parent passage. These are actual existing provider decisions, **not newly reviewed gold labels**. The original prepared expectations and stage-gate decisions remain unchanged. Source/result files are pinned by SHA-256; raw distributions and per-answer reuse provenance stay referenced in their original files. Natural video/block/time/segment locators remain at the linked input case's `source`. None certifies reviewed membership in a pastor's eligible corpus.

Synthetic evidence, claim shapes and counts are explicitly design-only. The G1-shaped case is a transport/consumer expectation for different objects/scopes, with real position availability set to `not_collected`; it does not implement G1. Scripture/style reuse is specified as a compatibility-gated reference to existing evidence, with an adapter still missing; this packet does not silently adapt or recollect those sources.

## What the packet should expose

The partial view is useful if a reader can identify the observed topic/mode/action or local directed relation/address, open the supporting passage, and see why position, recurring posture or depth remains unresolved. A01 prepares this view using narrow registry examples; A02–A09 exercise actual frozen decisions; A10–A17 cover context, independence, conflicts, rates, scope and local negatives.

The known G3 limitations are visible product behavior: care can be observed while recipient binding is unclear (A05); acknowledgment can be observed while relevance is unclear (A06); the busy-parent example remains withheld (A09). The packet does not repair those decisions. The positive challenge/warning example (A08) demonstrates that local multi-act evidence can also survive, with eligibility and recurrence still unestablished. Prayer about grief (A04) retains relevance and its God addressee without becoming human address.

If a future consumer can display only completed pastor traits, it fails this contract even when it suppresses false positives. If it can retain partial evidence but labels all missing fields zero or hides the desired richer characteristics, it also fails. Preserving unknowns is part of utility, not a substitute for showing the evidence that is known.

## Checks and exact handoff

From the repository root, Brian can run the prepared, provider-free check:

```sh
pte analysis profile-evidence-check
```

Focused development tests:

```sh
python -m unittest discover -s tests -p test_profile_evidence_packet.py
```

The check validates schemas, source hashes, exact frozen decisions, target/context grounding, provenance links, missingness, excluded/incompatible evidence, deduplication and inactive outputs. Ten focused tests cover attempted promotions/corruption. These checks passed during preparation. No dataset validation is required for this design handoff, and no provider or corpus evaluation was run.

**Packet-integrity PASS is not consumer-acceptance PASS.** The prose/JSON outputs are authored acceptance oracles; there is no consumer under test yet. A future consumer must accept each `Case.evidence`, explicit field requirements and coverage state, produce the expected `ExpectedView`, and retain all source/unknown links. A01/A10–A17 require judgment of the supplied visible wording against the stated expectations, in addition to exact state/reference checks; phrase matching alone cannot certify semantics. That adapter, rendering and acceptance execution require a separate implementation decision.

Brian's review is a concrete accept/reject of these prepared field meanings, visible examples and held claims. No annotation, case selection, experimental design or JSON authoring is assigned to him. After review, interpretation and a bounded next-step recommendation remain Codex's responsibility.

## Later tasks, without activation

| Later task | Required result before stronger use |
| --- | --- |
| Candidate discovery recall | Coverage audit beyond the curated candidate catalog; sermon-negative claims cannot rely on candidate non-detection. |
| Production calibration | Capability/semantic-version accuracy and abstention behavior on the intended deployment inputs. Bounded feasibility does not establish this. |
| Opportunity denominators | Reviewed definitions and capture of positive and negative opportunities, with unresolved units reported. |
| Request economics | Concrete reuse, batching, request/token/retry budgets and incremental costs for the separately proposed implementation. |
| G1 implementation | Separate explicit implementation decision; approved design remains uncollected and empirically unvalidated. |
| Collection and projection/comparison | Separate implementation/validation decisions, coverage and feature-specific sufficiency/uncertainty rules. No universal sermon-count cutoff is proposed. |
| G4 and quality | G4 separately designed/authorized; no coherence inference from this packet. No quality score is proposed. |

The recommended immediate review is of this contract and its partial-view behavior. Any follow-on implementation proposal should first demonstrate the provider-free supplied-evidence view and its limitations, before seeking broad collection approval. This does not reopen G2/G3 tuning.

## Authorized bounded consumer implementation — 2026-10-14

Brian subsequently authorized the provider-free observed-profile consumer behind
`pte`. The [consumer acceptance report](../../../evaluation/observed-profile-consumer-v1/REVIEW.md)
and [rendered views](../../../evaluation/observed-profile-consumer-v1/observed-profiles.html)
now exercise these same 17 cases with the frozen packet unchanged. Run
`pte analysis observed-profile-review` to reproduce them. Source/held-output
invariants pass in 17 cases; exact state/link expectations match in 15, with two
conservative differences disclosed in the report. The earlier implementation-hold
language above records the original design handoff; the later authorization applies
only to this bounded consumer. All G1/collection/projection/comparison/G4/scoring
holds remain. This does not activate the final PastorProfile projection layer.
