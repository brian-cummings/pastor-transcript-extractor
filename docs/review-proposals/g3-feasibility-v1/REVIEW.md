# Bounded G3 feasibility V1 handoff

Status: **prepared, not provider-validated**. G2 is closed as **bounded feasibility PASS WITH KNOWN RECALL LIMITATIONS**, per Brian's 2026-10-14 decision. This pilot tests C12's missing observation: what address is expressed, to whom, in relation to which circumstance. It does not measure inner empathy, advice effectiveness or pastor quality.

Run from the repository with the venv active:

```sh
pte analysis g3-feasibility-review
```

No input selection, annotation, JSON authoring or database setup is needed. The committed-to-workspace [input packet](input-v1.json), [readable cases](input-v1.md) and [exact question inventory](questions-v1.json) define the run. Provider credentials use the same configuration as G2. The command validates the frozen packet and questions before requests. It does not prepare new inputs silently. Inexpensive checks, without inference:

```sh
pte analysis g3-feasibility-review --check-only
```

`--prepare-only` explicitly regenerates the packet from the source catalog. After any intentional change, review/refreeze before validation; do not regenerate to conceal a changed source. No G3 provider validation was run while preparing this handoff.

## Candidate-builder design and scope

V1 uses a small, curated exact-span catalog rather than pretending an automatic circumstance/utterance extractor is already validated. Python copies source spans and preserves character offsets, source fields, full target text, leading/trailing context, archived video/block/segment/time locators and source-file hashes. Authored candidates come from the approved G3 contract fixtures; four narrow controls are declared in the pilot module. Natural candidates use literal spans selected in advance from three archived sermon passages. No semantic label is inferred by regex or supplied to the provider. Context-resolved circumstance candidates may come from leading context; utterances must occur in target evidence.

There are **21 cases / 27 candidates**: all 14 authored contract cases, four additional controls and three natural passages with two candidates each. Candidate endpoints can be within one sentence or across sentences; full target treatment remains available for reference and limits. This deliberately avoids the G2 mistake of confusing presence of candidates with good semantic decomposition. PTE will inspect the actual units on each mismatch.

Completeness means every prepared catalog candidate was presented and answered. It does **not** establish automatic candidate recall, complete episode boundaries or coverage of a sermon/corpus. An automatic candidate builder remains a later validation task. Natural episodes remain locally bounded excerpts, never certified complete sermons.

## Independent questions and consumption

The exact version is `g3-independent-address-and-circumstance-choice-v1`; [questions-v1.json](questions-v1.json) contains every instruction and criterion, not placeholders. Twelve independent Choice questions judge each candidate:

- Seven separate acts: acknowledgment, perspective-taking, reassurance, challenge, warning, invitation and concrete care. Each permits observed, not observed, incomplete and unclear. Multiple acts can coexist; counts are not substantive development or empathy.
- Circumstance binding: bound in target, bound with context-resolved identity, not bound, incomplete or unclear.
- Addressee: current listener (including conditional subsets), general/hypothetical person, reported person, God, no address or unresolved.
- Source voice: preacher, quoted/reported (including the preacher's retold speech), mixed or unresolved.
- Preacher stance: own/adopted, non-adopted report, explicitly rejected or unresolved.
- Local boundary sufficiency: sufficient, continuation required or unclear.

Act existence and circumstance binding are separate. A real invitation may fail circumstance binding; a reported challenge or reassurance can be real without being the preacher's current address. Prayer retains its own voice/addressee rather than inheriting listener address. Rejection cannot manufacture reassurance or another opposite act. Context can identify “this loss,” but cannot supply the act or connection. Other target sentences cannot manufacture an act in the specified utterance.

Every raw distribution is preserved. A selected probability below **0.80** becomes unclear; this inherited experimental threshold is not a corpus-calibrated guarantee. Provisional current-listener observations require an observed act, demonstrated circumstance binding, current-listener addressee, own/adopted stance and sufficient local evidence, each meeting the threshold. These are review aids only. General/hypothetical address and reports remain visible but separate. No projection executes. Qualifications/conditions remain visible in full source text; there is no new qualification extractor or listener-benefit field.

## Natural controls and existing evidence reuse

| Archived target | Contrasts and review expectation |
| --- | --- |
| Source/material V1, video 1200 block 32 | Busy life with children: explicit recognition of audience constraint versus the reported adversarial “keep them busy” plan. Acknowledgment does not establish actual empathy. Rhetorical framing remains reviewable. |
| Source/material V1, video 4430 block 57 | Scripture reassurance in a retold private conversation versus narration that he encouraged/prayed. Preserve reported person and retold voice; do not manufacture present audience application, actual addressed words from narration, or an effective outcome. |
| Listener-directive V3, video 590 block 64 | Real invitation to pray/participate versus the following address to God. Generic service participation is not acknowledgment or concrete circumstance-sensitive care. The mission/need relation is intentionally not treated as undisputed circumstance gold. |

This reuses exact archived material and locators, including already available Scripture/service evidence, without re-running Scripture, material or style collection to establish G3 links. Prior leaf probabilities, titles, identities, expected labels and review reasons are excluded from model state. No G1/G2/G3 answer is reused merely because the words are shared: the G3 question meanings differ. Voice/adoption design reuses G2's decomposition, while testing its semantics on G3 evidence.

Authored controls also cover topic-only grief, empathy self-description, perspective expression, qualified reassurance, acknowledgment plus challenge, invitation plus concrete care, rejected/historical reports, prayer, resolved versus leaking context, unresolved referents, warning plus challenge, wrong-object advice, proximity, cut-off care and non-adopted reported reassurance. The genuine act in a negative binding control must stay visible rather than being erased to make the control pass.

## Fixed execution and outputs

Pinned model: **jev-1.13.0**. One candidate per request, all 12 independent questions together. Maximum **27 uncached requests / 324 judgments**, timeout 45 seconds, zero SDK retries. No database/corpus traversal or progress monitor. Candidate/request economics stay on the backlog; this budget is a test bound, not a corpus-cost promise.

Exact state, complete questions/version, pinned model and source hashes identify cached responses. Raw distributions and usage are retained; malformed or wrong-model answers cannot be cached as valid. Re-running unchanged inputs uses cache. No cross-question semantic equivalence is assumed.

Expected artifacts:

- `evaluation/g3-address/feasibility-v1.results.json`: source-linked candidate rows, every raw answer, decisions, proposed observations, expected-label screens, input/question fingerprints and execution counts.
- `evaluation/g3-address/feasibility-v1.results.md`: all target/context/candidate evidence and every facet decision, including positives without authored expected labels. PTE must review these positives too.
- `evaluation/g3-address/cache-v1/`: successful source/question/model-bound responses.
- On execution failure: `feasibility-v1.execution-failure.json` and `.md`. Successful caches survive; an incomplete run has no semantic verdict. A prior results artifact is valid only for its own input fingerprint and completed execution.

No automatic PASS, pooled accuracy score, production row, pastor trait, empathy score or quality score is produced.

## Failure classification and acceptance proposal

Service failures, missing answers, corrupt/mismatched sources or malformed distributions are execution/integrity failures first; never semantic successes. After complete execution, PTE owns review of every expected-label mismatch **and every positive act/binding**, including unlabelled natural facets. Brian's role is to run the command and accept/reject a concrete interpreted recommendation.

Classify each semantic disagreement into exactly the same three buckets used for G2:

| Bucket | Meaning | Required follow-up |
| --- | --- | --- |
| A: contract/expected label | The proposed meaning, scope or expected label is debatable/wrong, including whether retelling is current adoption. | Resolve from evidence and approved contract; disclose changed expectations rather than retroactively claiming a model match. |
| B: candidate/boundary | Wrong circumstance, incomplete utterance or cut episode prevented the intended judgment. | Inspect exact supplied units/context; zero catalog omissions does not rule this out. |
| C: TypeSafe judgment | Evidence and contract are clear but the judgment is wrong. | Identify false binding/act, source/addressee/adoption error, context leakage or conservative recall loss separately. |

Proposed **PASS WITH KNOWN LIMITATIONS** requires all of the following after semantic review, not a percentage alone:

1. Complete, grounded answers for all 27 catalog candidates; source/question identities intact.
2. Every one of the seven act types has at least one reviewed positive authored observation, and the designed acknowledgment/challenge and invitation/care combinations remain independently representable.
3. Critical controls yield no confirmed false provisional current-listener observation: topic/self-description (G3-02/07), rejected/historical reports (08/10), prayer (09 and natural 590 prayer), context-only act (12), wrong object/proximity, cut-off care and report-only reassurance. Reported real acts remain visible as reported rather than erased. Correct gate arithmetic alone does not excuse systematically wrong semantic judgments.
4. Natural evidence shows at least one genuine adopted circumstance-sensitive address and correctly distinguishes the retold conversation and prayer/service contrasts. Candidate and stance ambiguities are adjudicated explicitly. A failure to establish any natural positive cannot be hidden by authored successes.
5. No systematic false circumstance connection, adoption or addressee transfer across controls. Remaining misses are conservative/concentrated or genuinely ambiguous; specific limitations and opportunity coverage are documented.

**Partial pass:** meaningful acts/bindings exist, but a required contrast/act lacks usable recall, natural positives remain unresolved, or isolated A/B/C issues prevent meeting a gate. Propose at most one justified revision with the same frozen cases plus narrowly needed controls; do not expand collection.

**Failure:** clear systematic false circumstance bindings, current-listener adoption of reports/prayer/context-only address, or inability to distinguish person-directed acts from nearby topics/service vocabulary. Stop expansion and revise the representation/candidate design before further feasibility claims. A single clear critical-control failure prevents PASS; whether it merits partial pass or failure depends on scope/systematicity after review.

A PASS establishes only the bounded observable-address architecture. Then compare G3/G2 evidence and decide a concrete next feasibility/implementation priority; G1 implementation/expansion still requires a separate decision. Full G3, G4, broad collection, projection, comparison and all pastor-quality scores stay held. Stop G2 tuning.

## Local verification

Provider-free preparation and integrity checks passed. Four focused harness tests and 17 CLI contract tests passed using unittest, including grounding/state isolation, source-stance/addressee gates, cache reuse, wrong-model rejection, visibility of unlabelled positives and mocked native CLI dispatch. Live TypeSafe Markdown docs were unavailable during this iteration; this isolated harness reuses the installed/previously checked G2 SDK adapter and Choice interface. No API additions or provider validation were inferred from inaccessible documentation.
