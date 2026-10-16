# Collector V4 recall repair — implementation review, 2026-10-16

**Implemented; ready for Brian's bounded provider-free development comparison. No development recall or fresh-confirmation result is claimed yet.** Brian [accepted Fresh V1 FAIL / G1 HOLD](../fresh-discovery-readiness-v1/acceptance-decision-v1.md), declined its paid run, and authorized this repair. The three Fresh V1 sermons and frozen references are development material only. V4 semantic-boundary raw FAIL / containment HOLD and accepted/closed A1 containment PASS remain unchanged; “Collector V4” is a separate collector version.

## What changed

A new source-only collector replaces lexical eligibility gates with bounded sentence-boundary hypotheses. The old collector, Fresh V1 inventory and references, semantic question factories, model, .80 gates, provenance requirements and admission/export/consumer modules remain unchanged. This is an alternate diagnostic collector, not activation of production collection.

**G2:** Citation spelling, book numbers and recent-citation scope no longer decide whether a sentence may be an anchor hypothesis. At every source sentence boundary, materialize both directed roles using widths (1,1), (1,2), (2,1) and (2,2). This preserves short interrupted quotations and complete glosses without requiring that lexical citation lookup succeeded. Up to two explicit gloss cuts preserve the entire prefix and suffix of a sentence, instead of taking disconnected clause fragments. Up to two nearest nonlocal gloss hypotheses are retained per origin within the unchanged frame limit, without a four-sentence horizon or a semantic ranking score.

This intentionally nominates nonbiblical material too. It does **not** label it biblical or explanatory. Source voice, actual explanation, adoption and admission remain downstream judgments under the unchanged safeguards. Wider anchor eligibility trades extra review work for recall; the comparison must disclose that work.

**G3:** Nominate every exact complete source sentence as a possible local utterance, including declaratives, imperatives, questions and reported quotations. Thus a finite list of `you/we/come/...` words cannot exclude an otherwise obvious act. Common abbreviation periods do not clip a sentence. At most one additional bounded continuation hypothesis per sentence retains referential/conditional continuation or a question followed by a short answer. Explicit reporting switches stop that grouping. Exact singleton targets remain separately available.

These groups are **continuation hypotheses requiring target review**, not resolved speech turns. A larger target may mix voices or neighboring acts; that risk remains subject to source review and unchanged measurement/admission requirements. The act phase still receives its exact candidate utterance, while the binding phase cannot introduce act fields. No circumstance mates are generated for this atomic-local diagnostic workflow. No circumstance claim is exported.

**G1:** Proof-topic surfaces nominate neighboring claim sentences with contiguous preceding/following framing inside the target. The unchanged eight-frame/six-phrase factory must accept the complete frame; it is never shrunk to force a fit. Overflow becomes a deferral. There are no new object options, relationship meanings, assurance judgments or A1 boundary exceptions. Topic false nominations are expected. This is narrow nomination/framing repair, not general theological G1 discovery or proof of semantic sufficiency.

No source IDs, reference spans, sermon phrases or expected answers occur in the collector. Source IDs enter only deterministic candidate identity. The source-only collector accepts text, main-span coordinates and policy; the separate comparison reads frozen references only after constructing new candidates and automatic envelopes.

## Bounds and safeguards

The existing hard limits remain **12,000 G2/G3 candidates per source / 20,000 aggregate; 200 G1 candidates per source; 6,000-character relation frames; 150,000 source characters / 300,000 aggregate**. The current diagnostic sources remain exactly the three already validated recordings. Bounds produce an explicit error/HOLD condition; no source or candidate truncation is allowed.

For N sentence nodes, G2 has a source-derived upper bound of **12N** (eight boundary hypotheses, two same-sentence cuts, two nonlocal mates); G3 has **2N** (singleton plus at most one continuation). Their combined bound is **14N**, with deduplication reducing actual counts. A source-derived bound can exceed the hard ceiling; actual materialization must still respect the hard ceiling. Extra same-sentence cut opportunities and nonlocal fanout are recorded as deferrals/diagnostics. This is not a claim that candidate growth is acceptable on the three sermons; that awaits Brian's run.

The current automatic-envelope materializer and request factories are reused without editing their pinned code. No provenance or sufficiency attestation is generated. Synthetic integration checks confirm that repaired G2/G3 targets materialize through the unchanged phase/question factories. No fresh measurements, receipts, review witnesses, admission-policy changes or semantic/provider runner are introduced.

## Development comparison and burden

The comparison uses the exact existing **97 definite opportunities**, with the two unresolved cases kept outside compatible denominators. It preserves the 47 controls. The old 41 misses are never silently replaced by easier checks. Results include, for each route and source:

- baseline and repaired complete-role/required-evidence upper-bound hits;
- every recovered, regressed and still-missing reference ID;
- actual candidate counts, source-derived bounds, deferrals and quota diagnostics;
- new role geometries, reference-unmatched candidates and contacts with the frozen controls;
- original new candidate targets and automatic envelopes for later inspection.

Unmatched candidates may be legitimate evidence outside the reference slate. Control contacts may be mixed or ambiguous targets. Neither is a semantic false-positive count or precision estimate. **Semantically false-positive candidate burden, certified safe-envelope recall, admitted yield and human review throughput remain unknown** until source/candidate review supports them. The comparison reports review-work proxies rather than inventing those measurements. No provider outputs exist.

Fresh V1 recall is **development recall only**. There is no new .80 development gate or requirement to recover all 41 misses. After results, Codex should assess whether the demonstrated failure classes materially improve, whether regressions matter, and whether candidate/control burden remains manageable under existing ceilings. A threshold-satisfying development result would still establish no held-out generalization, containment or collection readiness.

## Focused validation

Twelve synthetic collector tests cover novel imperative/question/reported surfaces, citation-free/misspelled anchor hypotheses, nonbiblical/narration controls remaining uncredited, complete same-sentence roles, interrupted two-sentence roles, nonlocal glosses, abbreviations, conditional Q/A continuations, reporting switches, G1 framing/pool preservation, deterministic IDs/bounds and unchanged request phases. Six harness tests cover recoveries/regressions, unresolved denominators, control-burden interpretation, metadata-only fresh selection and CLI authorization. All **57 focused tests passed**: these 18 new tests, 21 fresh adapter/proposal safeguards and 18 CLI contract checks. No diagnostic sermon comparison was executed by Codex.

## Exact handoff

The [input JSON](repair-input-v4.json) pins the repair implementation/tests, authorization, policy and unchanged reference bytes. [Implementation review JSON](implementation-review-v4.json) records checks and scope. Read-only input verification passed:

```sh
pte analysis collector-recall-repair --check-only
```

Brian's authorized dataset command:

```sh
pte analysis collector-recall-repair --run-development --approve-input f1a75376089cd79153524643d975d435b3598f33082de0026a4753cd22ebe780
```

This runs only the three retired Fresh V1 sources, makes **zero provider requests**, and writes sealed results under the configured application data directory:

`evaluation/collector-recall-repair-v4/f1a75376089cd79153524643d975d435b3598f33082de0026a4753cd22ebe780/results-v4.json` and `.md`, with a separate natural inventory. Existing results are reused only after seal/input verification; old Fresh V1 artifacts are not overwritten. Candidate-ceiling failures stop the run and preserve its inputs; report the error rather than increasing ceilings.

Brian only needs to execute the command and return its output. Codex owns the recovery/regression interpretation and next-step recommendation.

## Fresh V2 preparation after development review

A metadata-only selector is implemented behind `--prepare-confirmation --approve-development-result <reviewed fingerprint>`. It has **not run**. Codex supplies the concrete command after reviewing the development result; Brian is not assigned source selection or JSON work.

Selection uses SHA256 order with a new fixed salt, distinct source channels and the same duration/file/disposition/guest/title rules. It excludes all previous development channels plus all Fresh V1 primary/reserve channels and recordings. Three primaries and one technical reserve are selected without candidate or opportunity inspection. The selected manifest is sealed and reused, never refreshed because outcomes disappoint. Technical duplicate/boundary validation is still required before confirmation discovery freeze; the manifest alone does not authorize confirmation execution or create a reference census. New source-only candidates/envelopes must again be frozen before new full-source references.

Provider requests, semantic/admission changes, production collection, the 790-item V2 audit, automatic provenance attestation, recurrence/rates and pastor projection/comparison/scoring remain unauthorized. No V5 or reopening of closed development panels is proposed.
