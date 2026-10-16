# V1.1 execution authorization and handoff

Brian authorized one retired-source V1.1 development execution. Decision fingerprint: `327d84b3a306fec8239de4922ec5243c68413e525ff1747748be0217050e7b04`. Input: `1ab0ae15da7adf804a13fc2f6a4b88eb506a0210b1643e1a4f419ee9aa1ea170`. The reviewed input, implementation, historical results and review packet remain unchanged. Their execution-held fields describe the preparation snapshot; the new separate execution decision now grants this bounded run.

Read-only preparation verified the exact Python/platform/macOS and all locked package versions, all ten existing model artifact sizes/hashes, and source hashes/structural bounds. No model was loaded, no encoding or evaluation ran, no artifacts were downloaded, and provider requests remain zero. The actual loader repeats verification before deserialization.

Per `AGENTS.md`, Brian executes dataset validation:

```sh
pte analysis collector-retrieval-repair --run-development --approve-input 1ab0ae15da7adf804a13fc2f6a4b88eb506a0210b1643e1a4f419ee9aa1ea170
```

The reviewed `--check-only` message is a frozen preparation-status label and still prints `execution HELD`; it does not inspect the separate decision. The actual execution gate verifies `execution-authorization-v1.1.json`, the exact input/lock, one attempt, source IDs, resources and prohibited actions. No pinned CLI code or input fingerprint was changed to update that label.

All bounds remain unchanged: sources 520/1094/951 only; at most 16,100 G2/G3 candidates, 4,830 descriptors, 3,707,178 comparisons and 1,236,480 encoded tokens. Keep 8N/2N lane ceilings, 6,000-character frames/envelopes, 256 MiB per JSON file, 1 GiB aggregate JSON, 1,800-second cooperative per-invocation wall bound and documented source-level restart. No automatic retry, model substitution, download workflow or provider request is authorized.

Outputs belong under the configured base at `evaluation/collector-retrieval-development-v1.1/1ab0ae15da7adf804a13fc2f6a4b88eb506a0210b1643e1a4f419ee9aa1ea170/`. The complete natural inventory and diagnostic trace must seal before historical matching. A completed result is developmental diagnostics only, not readiness or containment acceptance.

After the run, Codex audits G2 representation/ranking/composition and exact targets/envelopes; G3 qualification/dependencies and every quota displacement; independent P1 quality, controls, burden and limitations. Historical V3/V1 diagnostics stay immutable. This is the final architecture-debug iteration: material losses versus V3 require reconsidering architecture, not further heuristic layering. G1 HOLD; no unseen confirmation, semantic inference/admission, collection, production, recurrence or projection/scoring is authorized.
