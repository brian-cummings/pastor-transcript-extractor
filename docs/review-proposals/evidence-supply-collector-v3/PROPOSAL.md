# Collector V3: source geometry and boundary proposal

**Authorized: provider-free design/prototype on the same six sources. No paid rerun, collection or projection.** This is collector V3, not a G1/G2/G3 construct revision. Brian accepted the [V2 FAIL](../../../evaluation/evidence-supply-readiness-v2/acceptance-decision-v2.md). All old inputs, expectations, answers and audit limitations remain unchanged.

The proposal is a two-layer collector: source episodes and exact role spans form the representation layer; bounded source-only searches nominate which role pairs to measure. A direct representation of a hand-authored case is never reported as successful discovery. `GEOMETRY_REVIEW.md` and `design-v3.json` disclose both layers.

## Concrete change

Retain full source sentences, add exact clause children for comma/semicolon/definition boundaries, and keep parent/source coordinates. G2 endpoints can be different clauses in one sentence. Overlapping endpoint roles are deferred, not treated as two propositions. Clause fanout beyond eight children retains the parent sentence and an explicit unresolved work item. This handles the demonstrated topology without interpreting punctuation as semantic truth.

Partition available text into contiguous approximately 4,000-character source episodes at sentence ends. These are retrieval containers, not semantic episode boundaries. Each episode and every sentence remains addressable. A role pair can be materialized at any sentence distance, with the full intervening source retained in a contiguous frame of at most 6,000 characters. If the relation or needed provenance exceeds that bound, defer the whole frame and preserve the required span; do not clip it or concatenate disjoint passages as if adjacent. The 36-node convicted-felon → bishop-promise relationship is represented without enumerating all pairs between its sentences.

The prototype's G2 search begins at explicit citations or sentence nodes within 700 characters of a recent citation signal. Book-of/citation syntax is required: a person named Mark or an ordinary job cannot become biblical evidence. This scope is an explicit retrieval heuristic, not a quotation-boundary or source-voice determination. Nonbiblical named sources are separate lexical signals. Reserve at most eight local-neighbor slots, two same-sentence clause slots and two long-range slots per G2 anchor. Long-range slots search up to three source episodes ranked by lexical overlap and source proximity. Same-sentence clauses cannot consume the long-range budget. G3 retains one generic act candidate per potential addressed utterance and at most five circumstance mates across up to three episodes. Expanded circumstance vocabulary handles demonstrated morphology/synonyms (fathers, dad, little ones, frightened, passed away, etc.); its coverage is development-selected and uncalibrated.

This produces a linear bound of `12 × G2 anchor count + 6 × G3 utterance count`, plus the 23 unchanged V2 G1 inputs if a later proposal includes them. The hard design ceilings are 12,000 candidates per source and 20,000 aggregate G2/G3 candidates. A ceiling violation blocks preparation; it does not silently truncate. Ranked-away pairs and episode references remain explicit retrieval work, not semantic negatives. No claim is made that a lexical top-k ranker discovers every relation in an episode.

## Attribution and candidate boundaries

A materialized frame preserves the exact named-source introduction when its lexical scope supports including it, instead of clipping it to 250 characters. Source voice remains null in collector metadata. A named-source hit does not resolve where a quotation ends, who adopts it, or which later sentence still belongs to it. A missing/stale/ambiguous signal therefore does not authorize preacher voice or Bible credit; source audit remains required. Source nodes and pinned snapshots retain the earlier material for explicit envelope expansion. R080's Desire of Ages introduction is physically retained; its proposed G2 admission is quarantined as a nonbiblical-source signal. The diagnostic still evaluates the wrong-voice/wrong-anchor error rather than hiding it behind a successful veto.

For G3, prepare two independent request shapes using the original question factories. The act/source phase has **exactly the candidate utterance as target**, with source attribution evidence only as context; it asks the existing seven act questions and source/recipient/stance/boundary questions. The relation phase supplies the larger contiguous circumstance/utterance frame and asks only the existing relevance and recipient-binding questions. It cannot introduce act fields. A pure combiner rejects wrong utterance/target identities or any act returned by the binding phase, preserves raw decisions, and never promotes an unclear act to observed. Conditions in the exact utterance remain verbatim; context cannot add an absent act.

Narration-only surface candidates (such as “I encouraged him and we prayed together” without actual addressed speech) are controls, with no positive export. A positive model answer on such a control remains an integrity finding even if export is blocked. This finite syntactic veto is conservative and can miss or over-quarantine other constructions. It is not a proof of semantic correctness and does not replace the closed G3 contract. Context may still contain neighboring speech, so the later semantic source audit must test leakage explicitly. No observation is automatically usable merely because the two-phase schema is valid.

No canonical question meaning, option, threshold, model or G1 composition changes. G2's five already-used fields remain the same; G3 splits their collection context while preserving independent question meanings. The prototype prepares diagnostic shapes only: it has no provider client, execution path, receipt-reuse permission or new spending authority.

## Provider-free result and remaining design limits

The current source-only prototype has **16,390 G2/G3 candidates**, against a source-derived bound of **18,798**, versus V2's 28,764 G2/G3 candidates. This is a bounded geometry measurement, not cost optimization or a provider-budget estimate. Source frames are referenced by exact coordinates and text hashes instead of duplicating every context body.

All **107 G2/G3 focal geometries** can be materialized by the frame builder; seven G1 checks remain on the unchanged V2 route. Those authored representations are not retrieval hits or successful semantic observations. Sparse automatic search retains 41 V2 exact focal matches, gains 10 and loses 27; 29 remain unsupplied. Its current exact automatic coverage is 23/62 G2 and 28/45 G3. Neither physical aliases nor manually supplied frames certify usable evidence. The missing/changed coverage and the naming/scope heuristics are explicitly preserved in the packet.

**Recommend reviewing this as a representation/boundary proposal, not accepting it as a replacement natural collector.** Its sparse ranker remains provisional. This iteration establishes source-aligned representation, bounded candidate growth and testable structural guards; it does not establish improved discovery recall, source-voice accuracy or prevention of every semantic leakage error. The full semantic boundary behavior must be validated on the new state shapes before any collection approval. No full-source paid rerun is proposed now.

## Forward check design

`CHECK_DESIGN.md` and `check-design-v3.json` propose source-backed forward controls for the two integrity failures and the documented expectation disputes. They do not rescore V2, revise its frozen oracle, discard ambiguous/negative controls, or certify unreviewed outputs. Existing focal expectations stay visible as historical diagnostics. Any repaired endpoint/allowed-value proposal is a new versioned check, pending a concrete follow-on packet decision.

Acceptance of a later collector design should require that demonstrated opportunities are representable with valid roles and provenance; no uncontrolled fanout, silent source truncation or contradictory field reuse occurs; and known critical controls remain explicit. It should not require recovering all 37 misses or maximizing populated fields. Retrieval regressions and remaining deferrals must be reviewed by opportunity type, not optimized to a single overall hit count.

A separately authorized semantic validation would first exercise a small prepared boundary/geometry panel—same-sentence G2, five/six-node G2, long-range G3, nonbiblical attribution, narration-only G3, generic and reported address, and safe withholding. Every positive/unscored-field failure requires source audit. Only after that and an explicit discovery-readiness decision should a bounded collection scope and V1 projection proposal be prepared. This document grants none of those steps.

## CLI and continuing holds

```sh
pte analysis evidence-supply-source-audit
pte analysis evidence-supply-collector-design --check-only
```

The first verifies the accepted V2 FAIL. The second reproduces the frozen provider-free prototype and diagnostics. `--prepare-only` renders the authorized packet; no paid flags exist on the design command. Brian reviews concrete inputs/results; Codex owns case selection and interpretation.

The 34 V2 certified focal items and $0.069 subset accounting ratio remain historical. The 790 non-reference positive outputs are still unaudited. Whole-run usable counts/unit costs, population recall, operational denominators, recurrence, G4/coherence, comparisons, clustering, quality scoring and pastor projection remain unestablished/held. The two V2 integrity findings do not isolate whether model behavior, context geometry or packing caused the errors; the contracts already prohibit those outcomes. No claim is made that engineering alone has proven them eliminated.
