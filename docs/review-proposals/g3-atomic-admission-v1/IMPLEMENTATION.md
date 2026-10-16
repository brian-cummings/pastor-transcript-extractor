# A1 implementation and provider-free replay authority — 2026-10-15

Brian approved A1 implementation **and** the bounded provider-free replay in one instruction. The historical [proposal](PROPOSAL.md) and its JSON are preserved as proposed, not rewritten to imply earlier authority. Current authority is [implementation-replay-authorization-a1.json](implementation-replay-authorization-a1.json).

The implementation uses distinct policy/item/witness versions. `g3_atomic_admission.Boundary` composes the unchanged V4 guard: it revalidates the original receipts and retains every reason except the broader shared boundary prerequisite for eligible atomic G3 claims. It then requires an affirmative accepted claim-specific witness. Definite continuation-required boundaries remain blocked. No raw answer is changed. G2 delegates to V4 and returns the identical typed item/wire.

The new typed `AtomicWitness` checks exact receipt/measurement/policy/source-envelope binding, every observed act, exact utterance support, source/recipient/adoption, complete qualifiers and explicit exclusions. Context may establish identity but cannot lend an act or qualifier. Missing or unknown witness completeness, incompatible provenance, unsupported extra positives, clipped targets and unsupported relevance/binding cannot be repaired by review. `AtomicLocalEvidence` re-admits on export, deserialization and consumption. A1 readers reject V4 G3 fallback; V4 readers reject A1 items. Duplicate evidence cannot inflate counts.

The [policy](policy-a1.json) pins the actual guard implementation. The [input](input-a1.json) fixes all 24 cases / 37 existing receipts, the original 40 runtime artifact hashes, seven critical fields and independently authored expected outputs. The source-controlled [trust root](replay-trust-root-a1.json) binds input, execution authorization and runner code. Fingerprint:

`7e8dbe1a65edc1eab2e98ab7edb9bbbe0468629ead2c0d761541bf7938dbca62`

The [claim review](claim-review-a1.json) contains only R018 and R053 witnesses. Codex separately reviewed their exact targets, supplied reporting context and broader source excerpts. The [claim-review acceptance](claim-review-acceptance-a1.json) transparently records delegated acceptance for this authorized local replay only. Brian explicitly authorized the controls and replay; this does not claim he personally inspected the newly authored files or accepted the final containment decision. The original V4 source review and its acceptance remain unchanged. This is a source-controlled safety oracle, not automatic attestation or general semantic override.

Focused verification: **84 distinct tests passed** across A1 guard (14), replay decision/CLI (9), V4 guard (16), historical proposal checker (11), V4 audit (11), CLI contract (18) and CLI reference (5). Tests cover real current/reported/G2 serialized consumption, boundary deferral, missing/unaccepted/foreign witnesses, unknown measurements, unsupported positives, context borrowing, clipped conditions, wrong namespace, receipt/envelope edits, post-load authority edits, schema mixing and duplicate evidence. Synthetic sealed receipts are confined to deterministic tests; the authorized replay reads only the original real receipt bytes.

```sh
pte analysis g3-atomic-admission-replay --check-only
pte analysis g3-atomic-admission-replay --execute --approve-packet 7e8dbe1a65edc1eab2e98ab7edb9bbbe0468629ead2c0d761541bf7938dbca62
```

Default/check-only performs no A1 admission execution or writes. Execution is an in-process local policy replay with no provider construction or retries. It writes `results-a1.json` under the configured application data directory at `evaluation/g3-atomic-admission-a1/`; repeated execution can only reproduce the identical result and cannot overwrite a differing artifact. V4 files are read-only inputs. The result preserves a pending independent source audit and final Brian decision; provisional automated success is not the gate decision.

Every emitted field and any unexpected admission must receive independent source review before a final recommendation. An unsupported/unresolved admitted item means FAIL; missing either G3 positive family means HOLD. Supported R018-current and R053-reported with unchanged G2 and zero unsupported/unresolved admissions permit a bounded A1 atomic-local containment PASS recommendation for Brian.

V4 remains raw semantics FAIL / containment HOLD with its original 22 quarantines. A1 outcomes belong to a separate policy namespace and report. No provider requests, semantic/threshold/ranker tuning, automatic provenance resolution, discovery/collection, 790-item V2 audit, recurrence/rates or pastor projection/comparison/scoring are authorized. A scoped A1 success would finish this development-panel containment question; the recommended next decision would concern discovery/readiness on fresh evidence, not another iteration on these 24 cases.
