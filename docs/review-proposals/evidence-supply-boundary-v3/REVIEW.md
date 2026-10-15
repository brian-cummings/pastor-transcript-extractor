# V3 small semantic boundary panel

**Brian authorizes this fixed panel only; Brian executes the CLI command. No full-source rerun.**

21 prepared cases, 33 maximum paid attempts, zero retries, `jev-1.13.0`. Public-list-price ceiling **$0.088704** from 33 × 64,000 reserved input tokens. Actual usage is not the reservation. Output is free at the frozen $0.042/M input price ([official pricing](https://docs.typesafe.ai/models), checked 2026-10-15).

Actual serialized request bodies: 4,048–16,183 UTF-8 bytes; total 280,448 bytes. This is payload measurement, not a tokenizer or actual charge estimate.

The accepted representation, source endpoints and canonical questions are reused. No ranker or G1 calls. Proposed forward controls are versioned here; V2 expectations/results stay unchanged. The repaired R058 anchor is explicitly new. All source-only search/recall limitations remain held.

## Cases

| Case | Source | Boundary class | Requests |
| --- | ---: | --- | ---: |
| B3-R021 | 421 | same_sentence_reading_control | 1 |
| B3-R023 | 421 | same_sentence_gloss | 1 |
| B3-R005 | 1200 | safe_withholding_diagnostic | 1 |
| B3-R003 | 1200 | six_node_G2 | 1 |
| B3-R004 | 1200 | six_node_G2 | 1 |
| B3-R008 | 1200 | five_node_G2 | 1 |
| B3-R080 | 350 | nonbiblical_attribution | 1 |
| B3-R043 | 4050 | nonbiblical_attribution | 1 |
| B3-R058 | 4430 | repaired_doubts_anchor | 1 |
| B3-R038 | 421 | long_G3 | 2 |
| B3-R092 | 350 | long_G3 | 2 |
| B3-R103 | 1046 | long_G3 | 2 |
| B3-R053 | 4050 | long_G3 | 2 |
| B3-R078 | 4430 | narration_only_control | 2 |
| B3-R018 | 1200 | generic_address | 2 |
| B3-R057 | 4050 | generic_address | 2 |
| B3-R073 | 4430 | reported_address | 2 |
| B3-R077 | 4430 | reported_address | 2 |
| B3-R111 | 1200 | reported_or_hypothetical_address | 2 |
| B3-R114 | 4050 | reported_address | 2 |
| B3-R076 | 4430 | God_address_control | 2 |

## Run

```sh
pte analysis evidence-supply-boundary-validation --paid-run-preflight
pte analysis evidence-supply-boundary-validation --execute \
  --approve-paid-packet 44a8d902e90fc5183a689c5f8bebcc052d45ff053fecf93f54c6482cbc01565b
```

Runtime receipts, ledger and results go under `<configured-base-dir>/evaluation/evidence-supply-boundary-v3/`, outside the repository. `--base-dir` overrides the application base directory. Progress prints before/after each request. Valid same-packet receipts replay without calls; failed/lost replies retain their reservation and stop for a separate recovery decision. A process lock prevents concurrent execution. V2 answers are never reused.

Read `CRITERIA.md` and `input-v3.json` for source-linked inputs, prepared expectations and the frozen decision rules. Codex audits every positive/unscored failure after Brian provides results. PASS permits preparing a separate discovery-readiness decision only; no collection or projection is activated.
