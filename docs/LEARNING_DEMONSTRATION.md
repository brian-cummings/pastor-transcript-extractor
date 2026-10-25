# Bounded automatic fingerprint preparation

`pte analysis learning-demo` is the V3 adapter over `pastor_evidence`,
`pastor_fingerprint`, `pastor_similarity` and `evidence_requests`. It preserves the
existing profile 318/V8, profile 130/P1 and exploratory Scripture benchmark commands.
The new fingerprint panel seam does not rank profiles or alter Scripture geometry.

Prepare the authorized six-recording panel without providers or database writes:

```sh
pte analysis learning-demo prepare --base-dir /Users/briancummings/Documents/PastorSearchData --proposal /Users/briancummings/Documents/PastorSearchData/evaluation/learning-work-package-v1/proposal-v3/proposal-v3.json --json
```

Add `--check-only` to reproduce preparation without writing artifacts. Preparation
validates proposal/companion/source hashes, current membership and source gates,
actual saved neighboring blocks, score-independent controls, compatible constituent
cache identities, and the 24 serialized source-reading requests. It freezes schemas,
prompts, model pins, topic measurements, source references, code identity, token
accounting, downstream batch construction rules and all phase reservations under
`<base>/evaluation/learning-demo-v3/<input-fingerprint>/input.json`.

`preparation.md` beside that file contains exact preflight, M5 and reporting commands.
`run --check-only` checks frozen implementation, membership/source/run lineage,
request identity and tokenizer accounting, without providers or attempt files.
Paid `run` requires the separate explicit `--experimental --approve-input <exact
fingerprint> --max-usd 2.00 --confirm-proposal-prices` decision and both credentials.
Do not execute that command as part of M1–M4. Current account access is unverified by
provider-free preparation. Price changes require a revised decision, never a larger
ceiling or replacement model.

All attempts reserve worst-case phase cost before sending; receipts are immutable,
cache reuse is exact, retries/fallbacks are zero, and uncertain spend stops the entire
run. All dynamically generated batches undergo request and per-question fit checks.
Input/output overflow stops explicitly; it never strips qualifications or adds batches.
The local OpenAI tokenizer reuses the pinned installed runtime and encoding cache,
without importing the closed source-probe controller. TypeSafe uses a conservative
UTF-8 byte upper bound plus framing at the default 32k-question/64k-request limits,
reserving 65,536 charged input tokens. No long-context opt-in is used.

Automatic observations use the existing literal compiler under a machine-origin
contract. Literal checks and verifier probabilities do not establish human review or
production admission. Raw observations, failed bindings, unresolved assignments,
first narratives and removed clauses remain available. Fingerprints retain qualified
meanings, adopted affirmation/denial/unresolved sets, original observations, source
coordinates, independent uncertainty categories and separate topic estimands.
Parent metrics pool unique IDs within one operator; there is no overall score.
Relation absence requires an explicitly assessed matched-endpoint opportunity.

The same deterministic builder serves candidate and reference inputs. Production
requires a separate evidence policy; experimental records cannot pass it. The
benchmark adapter supplies SampleSpec/EvidenceView inputs to the same kernel rather
than accepting authored reference theology.

Interpretations require at least two supported, aligned premises, exact scope,
alternatives and defeaters, plus semantic checks. Substantive narrative clauses use
structured entry IDs and their complete dependency closure. Failed clauses are
removed once; generation never repeats until it passes. All six recording-omission
views rebuild evidence sets, measurements, masks, comparisons and supported
hypotheses. Old pair prose is withheld after numerical inputs change.

`report` shows preparation state or persisted run accounting and source-stratum
coverage. Its optional `--audit` is an offline M6 consumer, excluded from every runtime
model request. Blinded reference tags drive family/complexity retention, false
rejection, coverage, descriptive Wilson intervals and selective-loss diagnostics.
An audit packet is prepared by Codex after the separately authorized run; Brian is
not assigned JSON authoring or source annotation. Runtime repair/approval remains
zero. Semantic PASS needs all acceptance components and adequate independent
reference denominators; component FAIL and source/reference INCONCLUSIVE remain
distinct. Stubbed workflow success does not establish theological accuracy.

Focused provider-free development checks:

```sh
PYTHONPATH=tests python -m unittest test_pastor_evidence test_pastor_fingerprint test_evidence_requests test_learning_demo test_learning_demo_cli test_theological_binding test_profile_evidence_supply test_profile_explanatory_descriptions test_profile_presentation test_profile_portability test_benchmark test_cli_contract
```

No corpus classification, dataset comparison, reclassification, cohort collection,
closed-experiment execution, production materialization or admission change belongs
to this preparation slice.
