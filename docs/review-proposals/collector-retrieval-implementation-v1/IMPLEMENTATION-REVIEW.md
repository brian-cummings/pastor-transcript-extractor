# Collector retrieval/composition V1 — implementation review

**Bounded implementation complete; P1 accepted prospectively. Recommend separate authorization for runtime preparation, locked-model acquisition and the three-source provider-free development run below.** No model artifacts were downloaded or loaded, and no runtime packages were installed; no encoder inference, retired-source evaluation, provider calls or fresh-source selection occurred.

This report establishes implementation checks, not discovery readiness, semantic accuracy or general containment. Fresh V3 remains accepted scoped FAIL / G1 HOLD. Source-unit Repair V1, historical references/results, semantic questions/options/.80 gates and A1 admission remain unchanged. The original proposal remains an immutable proposal-only record; Brian's new [implementation authorization](implementation-authorization-v1.json) separately approves implementation and [P1](P1-policy.md).

## Implemented behavior

The new implementation is beside the frozen collector, with no production dispatch change:

| Component | Behavior |
|---|---|
| `collector_role_lattice.py` | Uses unchanged source units as indexing leaves. Proposes exact clause/core and dependency-completion spans above/below those units. At most three descriptors/unit, with canonical feature→complete-role mappings. |
| `collector_retrieval.py` | Separate G2 local-composition, within-unit partition and source-wide concept lanes; separate G3 core/completion selector. Direction has distinct identities. No semantic truth, source/recipient/adoption or pastor credit is assigned. |
| `collector_retrieval_encoder.py` | Offline adapter for the upstream original float32 ONNX export of the one approved MiniLM model. Loading requires authorization, runtime-version/platform checks and exact local artifact verification. No network/model-hub API exists in the adapter. |
| `collector_retrieval_workflow.py` | Read-only verification/structural preflight; separately gated artifact acquisition and retired-source execution; locking, immutable atomic source checkpoints, sealed inventory before reference matching and source-only result output. |

The structural grammar is deliberately limited: generic clause boundaries, gloss signals, reporting introductions, conditions, content completion and suspected scope changes propose hypotheses. Reporting introductions may be context-only. Detected conditions/qualifications stay attached; a ranking feature representing a piece of a detected completion maps back to the full role, never a detached exported fragment. Dependency completion blocked by a suspected source switch or frame limit is deferred. The logic does not establish that every real dependency or speech boundary is recognized.

G3 retains at most two structural act hypotheses per unit. Excess cores are recorded with exact source spans and reason `G3_two_per_unit_saturation`; the runner exposes per-source `G3_budget_displacement`, including per-unit saturation, eligible/retained/displaced counts and separately blocked dependencies. These are **unmeasured act hypotheses**, not confirmed good acts or a measured recall denominator. Repetition retains distinct occurrence coordinates; no recurrence/event-count credit is created. Nested speech, prayer and narration never gain provenance authority from a parse or rank.

G2 replaces the old selection budget rather than appending windows: ≤2N local directed pairs, ≤2N partition pairs and ≤4N concept pairs. Seed-role features form one mean query per unit; each query ranks source-local descriptors, chooses at most two distinct remote mate units and emits both orientations. There is no gloss-vocabulary or nearest-distance requirement for that lane. Displaced mates, duplicate geometries, unavailable ranking descriptors, overlap and frame exclusions are counted; there is no quota refill after duplicate/representation loss. A high rank remains a candidate hypothesis, including topic-similar distractions.

Automatic envelopes preserve exact targets, named attribution and a nearby structural reporting introduction, with optional neighboring context within the existing bound. Their source voice, recipient scope, reporting completeness and sufficiency remain unknown. Missing distant identity/context is a source-audit limitation; this is not automatic provenance resolution. No usable-evidence export path or accepted review witness is created by discovery.

## Exact artifact and runtime lock

[artifact-lock-v1.json](artifact-lock-v1.json) locks:

- Model: `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- Original `onnx/model.onnx`, **90,405,214 bytes**, SHA256 `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452`.
- Tokenizer, vocabulary, model/sentence-transformer/pooling/module configs: exact sizes and upstream Git blob SHA1 values. Verification computes SHA1 over Git's `blob <size>\0<bytes>` encoding, rather than confusing blob IDs with plain-file SHA1. All ten selected files are verified before loading. LFS weights use SHA256.
- Exact 24-package transitive runtime and compatible wheel SHA256 values in [runtime-requirements-v1.lock](runtime-requirements-v1.lock). Core versions: ONNX Runtime 1.23.2, tokenizers 0.22.1, NumPy 2.4.6; CPython **3.11.15**, Darwin arm64 / macOS **27.0.1**. A different runtime requires a new reviewed lock rather than silent fallback.
- CPU-only sequential session, one intra/inter-op thread, graph optimization disabled, batch size one; attention-mask mean pooling and L2 normalization; 384 dimensions. Ranking uses Python `math.fsum` cosine rounded to six decimal places and canonical coordinate/parent tie order. Bit identity across other hardware/platforms is not established.

The [upstream model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) identifies semantic-search embeddings and a default 256-word-piece truncation limit. This adapter disables truncation and checks the complete tokenized ranking descriptor, including special tokens. Over-limit descriptors receive no vector and an explicit ranking deferral; no lexical fallback is substituted. A smaller declared ranking feature can map to a complete canonical evidence role. This does not clip the measurement target.

The lock was prepared from immutable [Hugging Face revision metadata](https://huggingface.co/api/models/sentence-transformers/all-MiniLM-L6-v2/revision/1110a243fdf4706b3f48f1d95db1a4f5529b4d41?blobs=true) and PyPI version/wheel metadata. **Metadata was read; artifact content was not downloaded or verified locally.** Real tokenizer behavior, ONNX input/output compatibility, runtime installation and actual performance therefore remain unexercised. Shape/version/hash mismatch fails closed before any development score can be reported. The adapter follows the official [ONNX Runtime Python API](https://onnxruntime.ai/docs/api/python/api_summary.html) and [tokenizer API](https://huggingface.co/docs/tokenizers/api/tokenizer).

## Verification evidence

Focused checks: **72 tests passed** across the retrieval/design tests (19), frozen source-unit tests (16), unchanged A1 synthetic admission/export/consumer tests (14), and CLI contract/reference tests (23). The retrieval tests use injected vectors and small synthetic sources only. No real encoder inference or dataset evaluation was hidden inside testing.

Coverage includes exact Unicode/unpunctuated coordinates; same-unit partition and reverse direction; detected complete roles across units; non-gloss remote retrieval with injected ranks; similarity without semantic authority; unchanged frame bounds; conditional/qualified targets; independent commands; repeated occurrences; report/prayer/nested/narration scope uncertainty; explicit G3 saturation; ranking token overflow; masked pooling; artifact digest mismatch; CLI hold enforcement; immutable checkpoints and synthetic seal-before-match/restart behavior. Tests also show candidate metadata, even with fabricated positive fields, cannot enter the existing typed consumer directly. The unchanged A1 tests exercise its actual supported-positive and incompatible-positive guard/export/consumer paths.

These tests do not prove that the heuristic lattice finds every legitimate act, that embeddings recover conceptual explanatory links, that a target is source-compatible, or that future raw outputs will be admitted. They also do not extend A1's accepted bounded semantic result to new evidence. Existing Fresh V3 review bindings verify unchanged, including its source-review fingerprint `ad0f1c16f94909ba5be8429ca86d503b5241ecde8f9451fcf754f9ea6986bf8a`.

## Prepared development packet and resource proposal

[development-input-v1.json](development-input-v1.json) binds exactly the three retired V3 sources **520, 1094, 951**, their canonical snapshots/hashes, unchanged historical references, new implementation/tests, frozen baseline/admission files, P1 and the artifact lock. No other sources or fresh selection are part of this command.

Structural preflight formed only the unchanged bounded source units. It did **not** build the new lattice, generate candidates, open references for matching, tokenize, encode or run development evaluation.

| Source | Frozen units N | G2/G3 candidate upper bound | Descriptor upper bound | Comparison upper bound | Encoded-token upper bound |
|---|---:|---:|---:|---:|---:|
| 520 | 111 | 1,110 | 333 | 36,963 | 85,248 |
| 1094 | 526 | 5,260 | 1,578 | 830,028 | 403,968 |
| 951 | 973 | 9,730 | 2,919 | 2,840,187 | 747,264 |
| Total | 1,610 | **16,100** | **4,830** | **3,707,178** | **1,236,480** |

Bounds remain G2 ≤8N, G3 ≤2N, descriptors ≤3N, G2/G3 ≤12,000/source and ≤20,000 total, G1 ≤200/source, frames/envelopes ≤6,000 characters, and ≤8,000,000 exact vector comparisons/source. The 16,100 value is a proof ceiling, not an observed candidate count. G1 nomination logic is unchanged; preflight checks its ceiling separately. Ranking over-limit descriptors can reduce indexed coverage; that loss must be audited rather than treated as model withholding or absent opportunity.

The cost/resource proposal is:

- **Provider requests and paid model API cost: 0 / $0.** No Jev calls, semantic request queue or admission run is included.
- At most **91,104,751 bytes** of selected model/config artifacts and **38,891,385 bytes** of locked wheels (129,996,136 bytes combined, excluding protocol/package-manager overhead and pre-existing cache reuse). Wheel hashes are enforced by the proposed installation command. Installed package provenance is additionally subject to the local environment; the loader verifies exact package versions, not a signed attestation of installed code.
- Batch one; comparison/token/descriptor ceilings as above per complete attempt. RAM and real CPU duration have not been measured. Python vector storage, ONNX workspace and result serialization add overhead beyond the raw embedding matrix; no measured memory claim is made.
- Cooperative **1,800-second wall-time checks per invocation**, including lattice/encoding/ranking boundaries. This is not an operating-system hard kill and cannot interrupt a hung native call immediately. Completed source checkpoints can resume without re-encoding those sources; an interrupted unsealed source is recomputed. There is no automatic retry loop. Repeated manual invocations can consume more total CPU/tokens than one attempt; they do not incur provider spend.
- Maximum **256 MiB per sealed JSON output**, **1 GiB sealed JSON outputs per fingerprint directory**. The output cap fails before writing an oversized artifact. Temporary files and package/model cache are separate from that cap. Immutable completed results are reused after binding checks; altered checkpoints fail closed.

Model acquisition validates exact size/digest before promoting a partial file. Interrupted partial downloads can be replaced by another authorized acquisition attempt; a corrupt published artifact is rejected. Source checkpoints/inventory/results are atomically sealed under a nonblocking filesystem lock. All runtime outputs/cache live under the configured application base directory, not the repository.

The automatic result will be `DEVELOPMENT_DIAGNOSTIC_ONLY` / G1 HOLD. It seals the natural inventory before reading references for matching, reports unchanged historical exact-target/required-span diagnostics and workload, and prominently exposes G3 displacement. It neither rewrites historical results nor creates new P1 gold automatically. Codex must then audit the actual target/envelope supply, controls, missing opportunities, candidate density/distribution, ranking/resource losses and P1 granularity in a separate development ledger. No requirement to recover all old misses is introduced.

## Fingerprints

- Implementation authorization: `eac9c30460ef9420e46f5343849dcbddc843d5772bf07cb35b9cee56681d8830`.
- Artifact/runtime lock: `28c31ab7a6e18f035eefcea14c0aa24104dad5ad057084c2f53f57616830fb7a`.
- Development input: `85dc5c4bc714c9b839ed7fb2371eec9a247ad4202a7c3a10c22b74b0d6b024ac`.

The machine-readable [implementation review](implementation-review-v1.json) binds the report, input, authority and lock. These hashes bind a review; they are not automatic semantic attestation.

## Commands and requested decision

Safe now:

```sh
pte analysis collector-retrieval --check-only
pte analysis collector-retrieval --preflight
```

**The following commands are prepared for a later authorization; do not execute them yet.** They require a new source-controlled execution decision bound to the exact input/lock. The current CLI intentionally rejects acquisition/development because that decision is absent. Runtime installation is also part of the requested later approval, not work performed here.

```sh
python -m pip install --require-hashes --retries 0 -r /Users/briancummings/code/pastor-transcript-extractor/docs/review-proposals/collector-retrieval-implementation-v1/runtime-requirements-v1.lock
pte analysis collector-retrieval --acquire-model --approve-input 85dc5c4bc714c9b839ed7fb2371eec9a247ad4202a7c3a10c22b74b0d6b024ac
pte analysis collector-retrieval --run-development --approve-input 85dc5c4bc714c9b839ed7fb2371eec9a247ad4202a7c3a10c22b74b0d6b024ac
```

**Recommendation:** authorize this exact runtime/model preparation and one bounded provider-free retired-source development attempt for Brian to execute, with source-level restart reuse as described. This tests the substantive new mechanism before another unseen confirmation. Keep model comparison/training, collector tuning toward individual references, automatic provenance, semantic/admission/threshold changes, provider inference, fresh-source selection, collection, recurrence/rates, production use, the 790-item audit and pastor projection/comparison/scoring held. A later new-source confirmation needs a separately reviewed implementation freeze and authorization.
