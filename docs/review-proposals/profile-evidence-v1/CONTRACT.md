# Shared evidence / field contract V1

This review contract bridges the [desired C01–C20 specification](../../PASTOR_PROFILE_GAP_ANALYSIS.md) and the [existing 59-leaf registry](../pastor-contracts-v1/REGISTRY.md). It preserves each source contract's narrower meaning and allowed uses. [Schema](schema-v1.json) and [complete examples](packet-v1.json) define the exact V1 packet wire shapes; the rules below add cross-record semantics. Production storage migrations and source adapters are not implemented.

## Source and unit identity

Every observation carries a source snapshot, exact half-open character spans `[start,end)`, span roles, segment/time locators where available, and explicit unknown locators where unavailable. Character offsets are Unicode code-point offsets into the named source field, not byte offsets. `target_sha256` hashes UTF-8 target text. `transcript_sha256` refers to the full transcript version only when actually known; a target-window hash must never impersonate it. The packet has no full-transcript snapshots, so that field is null. Source text changes invalidate span identity until explicitly reconciled.

Packet IDs are stable authored aliases within V1. A later production adapter must derive source-scoped unit/utterance IDs from recording identity, transcript version, role and spans, and observation IDs additionally from semantic question/run identity. Different questions over the same spans remain different observations with a shared independence group. An adapter must not treat a new run as a new underlying utterance.

Candidate, utterance, node/edge and episode identities remain distinct. `local_boundary=sufficient` certifies only the supplied local judgment scope. It does not certify a complete developed episode, sermon or recall. Episode boundaries may be proposed, complete after review, or unknown; duration and episode counts require appropriate boundary review. Reviewed negatives apply only to the named assessed unit.

Leading/trailing context can resolve identity, such as “this loss,” while the target supplies the act and its connection. A relation's endpoints and the address utterance must be target-grounded. Context-only acts cannot be imported. Original segment/time locators remain available through the source reference when the packet carries character spans only; fabricated time precision is forbidden.

## Provenance, reuse and compatibility

Preserve capability, exact question semantics/version/digest, candidate builder, requested and actually resolved model, raw distributions, original decision policy, source/review status and answer origin. Experimental 0.80 decisions are frozen facts about these runs, not a new production threshold. Unknown model resolution remains unknown; requesting a model is not proof of resolution. Per-answer reuse references are normative because a V2 row can contain unchanged V1 answers. A top-level V2 digest must not replace those original meanings.

`synthetic_design` means no observed provider or pastor evidence. `frozen_provider_output` means an existing run, not semantic perfection or production eligibility. The source hash list freezes the original artifacts, and each record links to its exact input/result pointers and raw/per-answer provenance. Do not rewrite historical mismatches into matches. Question compatibility must be established by exact meaning, not a common label or temporal overlap.

Existing Scripture and legacy style anchors may be referenced by their original source/run/segment and semantic contract after compatibility review. An unverified passage match is not a verified citation. Existing leaf evidence retains canonical questions and all registry restrictions. This V1 packet includes registry, relation, address and **design-only** claim payload shapes; structural-anchor adapters remain absent and visible in C09/C16. Equivalent source evidence should be reused when compatible rather than recollected to fit a new transport shape.

## Ownership and attribution

`membership`, content eligibility, policy version and review reference describe effective reviewed decisions; they are not inferred from the provider's voice/adoption answer. An adopted statement is still ineligible pastor evidence if the speaker membership/content gates fail. Conflicts and excluded content stay visible in the evidence archive, with pastor-field credit withheld. Unknown eligibility permits a **supplied-passage example**, with attribution withheld; it does not permit a pastor assertion.

This packet's `FieldEvidence.subject_scope` is always `supplied_passage`. Reviewed membership in synthetic cases is authored design input only. Frozen pilot examples explicitly have unknown real membership/content eligibility and no independently eligible sermon count. A future pastor view requires explicit reviewed attribution plus the stronger field's other gates.

## Independent meanings inside the envelope

| Payload | Meaning preserved | Stronger claim withheld |
| --- | --- | --- |
| `leaf` | Canonical contract ID and its permitted observed statement | Richer positions, development and posture absent from that leaf |
| `claim_design_only` | Object, relation, expressed polarity/uncertainty, conditions, voice/adoption | Real G1 measurement, opposite claims synthesized from rejection, cross-scope contradiction |
| `relation` | Directed endpoints, named facet, local relation decision and separate voice/adoption | Adequacy, depth, fidelity, full interpretive method and complete episode |
| `address` | Seven independent acts, circumstance relevance, human-recipient binding, addressee, voice/adoption and explicit qualification | Inner empathy, benefit, global posture and quality |

An empty qualification list means no explicit qualifier is supplied for this local example; it does not mean universal/unconditional teaching. A reported or rejected act remains searchable evidence. Rejection does not create its opposite. Shared words and compatible voice infrastructure do not make G1 claim adoption, G2 relation adoption and G3 address adoption interchangeable observations.

Current-listener address composes an observed act, positive relevance, positive human-recipient binding, current-listener addressee, own/adopted stance and sufficient local evidence. Context-resolved positives retain that provenance. A withheld component leaves the other observations intact. Prayer can be relevant while human binding is negative. A reported recipient can be bound without becoming a current listener. The act set is multi-label, not a kindness scale. Composition is an acceptance rule here; no new collector or pastor projection implements it.

## Independence and coverage

Retain underlying utterance, episode, duplicate-recording, independent-sermon, repeated-material, series and period groups. Overlapping candidates and duplicate uploads share underlying occurrence groups. Different facets sharing wording are different observations, not independent corroborations. A repeated illustration in two actual sermons remains two sermons sharing material/series dependence; do not collapse all same-series sermons into one or call them independent thematic replications.

The packet's `unique_utterance_groups` is a check on the supplied aliases, not estimated effective sample size. `independently_eligible_sermons` is null for frozen/mixed cases and design-only for synthetic cases. Series/period metadata stays visible; unknown dates are not upload dates. No numeric recurrence threshold or effective sample-size formula is established.

Candidate discovery, local boundary, episode boundary, sermon assessment and opportunity coverage are separate axes. A complete frozen catalog is not automatic discovery recall. Neither full local sufficiency nor many positives establishes an opportunity denominator. Contrasting passages remain visible without being forced into a contradiction or a scalar score.

## Field evidence and missingness

`FieldContract` defines the desired characteristic question, target statement, estimands, compatible inputs, required gates, missing information, packet claim ceiling and forbidden inference. `FieldEvidence` is a scoped proposed display: interpretation version, estimand, availability, claim level, support/counter/unresolved links, absent required inputs, suppression reasons, visible statement and uncertainty wording. Follow the links to inspect original source, coverage and independence; do not duplicate weaker metadata as stronger derived facts.

| Availability | Display requirement |
| --- | --- |
| `local_examples` | Show the supported observation and source, with stronger claims explicitly withheld. |
| `negative_in_unit` | Show absence of a specified act/facet in the reviewed complete local unit only. |
| `not_collected` | Name missing observation types, especially held G1. |
| `measurement_unresolved` | Preserve the three unavailable salvation relationships; never serialize them as zero/negative. |
| `judgment_withheld` | Retain observed facets and unresolved relation/framing decisions independently. |
| `boundary_incomplete` | Name continuation/boundary requirements; do not use as a negative. |
| `incompatible` | Identify semantic/source-version incompatibility; no silent pooling. |
| `excluded` | Show eligibility/ownership exclusion and review reason. |
| `downstream_held` | Name the separate decision/construct, such as G4. |

Unknown candidate recall/opportunities are orthogonal coverage states, not a replacement for any of these. A valid local negative is not missing data; missing data is not a negative. Model uncertainty is not the pastor expressing uncertainty. Empty support is not an inferred contrary position.

Future reviewed-sample patterns, recurring characterizations and comparative constructs need separate claim levels, versioned sufficiency/uncertainty gates and implementation authorization. V1 outputs reserve those values as null. A provider-free consumer pass would establish behavior on supplied evidence only; it would not prove measurement accuracy, automatic discovery, population inference or profile validity.
