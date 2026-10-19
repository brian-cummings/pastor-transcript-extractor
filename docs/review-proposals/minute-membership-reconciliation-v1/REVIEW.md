# Minute-block membership reconciliation

**The source-window precedence conflict is resolved for the authorized retired fixtures.** The adapter now prepares **24/24 diagnostic slots**, including the five previously deferred slots. These produce **17 distinct contexts / 18 G2/G3 family/context bindings**, with no remaining membership deferrals. No inference or admission was performed.

The original **19/24** packet is preserved with fingerprint `cf57f22066a32a18c26165fe3ea239271d52627cd3531679c78df7fc49b5a769`. Its result was correct for the saved-membership policy; this new version does not rescore or overwrite it.

Reconciled preparation fingerprint: `84ae2ce9dc0abd1bfd22a82a192df3a457fe9bae898a7dbab4eec163b8e5e7cc`.

Generated preparation: [preparation-v1.json](/Users/briancummings/Documents/PastorSearchData/evaluation/minute-membership-reconciliation-v1/84ae2ce9dc0abd1bfd22a82a192df3a457fe9bae898a7dbab4eec163b8e5e7cc/preparation-v1.json).

## Explicit precedence, not a silent window change

The default remains the saved extraction's retained segment indexes. A source review alone does not activate an override. The reviewed mode requires [authorization-v1.json](authorization-v1.json), bound to the original preparation, exact source snapshots, exact persisted extraction bytes/content, and the frozen source-validation review `f36f8090fe84ed5f6fa7e68f428a5bb0588b2e3732b742b0c02bc558ca77759b`.

Under that explicit authority, **replace** saved fixture membership with complete canonical normalization units inside each reviewed main interval. Do not union the sets: union would retain introductions/prayers/host material that the source review explicitly removed. Units crossing an interval boundary remain excluded, rather than inventing word-level membership. The mapping/context adapter still requires a whole, exactly mapped center inside the reviewed interval.

| Source | Saved segment count | Effective fixture count | Added | Removed | Boundary unit deferred |
|---|---:|---:|---:|---:|---|
| 520 | 2296 | 2279 | 0 | 17 | 520:F0001 |
| 1094 | 1490 | 1772 | 283 | 1 | 1094:F0007 |
| 951 | 2051 | 2941 | 1071 | 181 | 951:F0010 |

These are segment-provenance counts, not evidence counts or observations. The policy applies consistently to all three fixed sources, not only the five misses. Original extraction JSON, segment labels, source text and the database were not changed. Source 520's manifest ASR/caption discrepancy is still disclosed; canonical text is verified from the actual caption extraction.

**Authority is limited to retired fixture preparation.** It does not change production membership or certify nominal pastor identity. Earlier source review notes explicitly limit speaker ownership, and those limits remain intact. A production workflow would require its own accepted window/membership binding, not this study-specific override.

## What changed in the five slots

The original source-951 extraction stopped retained membership at **2608.4 seconds**. The frozen source study had restored the continuous later sermon after determining that old end stopped mid-sermon reported conversation. The effective study overlay now follows that already reviewed main interval while preserving both original artifacts.

- **CE-03**: taken/left G2 pair now has context [37543,42752), 5,209 characters.
- **CE-05**: current trust admonition has context [52379,57354), 4,975 characters.
- **CE-07 and CE-16**: outer exhortation/model-speech diagnostic slots share context [47986,53744), 5,758 characters.
- **CE-24**: unresolved neighboring-speaker control locator has context [52897,57448), 4,551 characters. Context availability does not resolve its speaker or turn it into preacher evidence.

All 24 diagnostic focal/support footprints fit their prepared envelopes, ranging from 3,641 to 5,999 characters. This is geometric source supply, **not semantic recovery, discovery recall or containment**. Context may include source outside the effective center membership, including neighboring host material; it remains context-only, cannot independently earn old center-target measurements, and cannot confer ownership. Exact nomination/semantic review is still required.

No alternate anchors, reference edits, model judgments, enlarged context caps or qualifier repairs were used to obtain these changes. The existing context policy and canonical mapping/validator remain unchanged.

## Binding and safety

Every reconciled anchor contains its effective-membership fingerprint and scope. Context, routing and preparation identities therefore change when the authority changes, even if the effective index set happens to be identical. Nothing can inherit a provider cache entry merely because the source words match. The prepared records still say inference, measurement, admission and provider-cache reuse are disabled.

The overlay fails closed on changed source, extraction, review, review bounds, authority or scope. The three boundary-crossing normalization units remain excluded. Unknown source ownership stays unknown. No source review becomes an automatic V4/A1 witness or production permission.

## Verification and CLI

**76 focused tests passed.** New tests cover default saved membership, explicit replacement versus union, removal as well as restoration, immutable old artifacts, stale/foreign bindings, invalid production/provider scope, boundary-unit exclusion, authority-sensitive identity and explicit CLI selection. Existing mapping/context/nomination, historical CLI and probe-retirement tests also pass.

Read-only check of the new reconciled fixture packet:

```bash
pte analysis structure-readiness --check-handoff --reviewed-membership --json
```

The same command without `--reviewed-membership` checks the preserved 19/24 baseline. Its historical CLI byte pin is verified against Git `42f1fb6`; no old packet is rewritten to accept new code. To reproduce only this small provider-free reconciliation:

```bash
pte analysis structure-readiness --prepare-handoff --reviewed-membership --json
```

The prepared data stay under the configured application base directory. There are zero provider requests, zero model loads, no Jev calls, no changed classification/source/database records and no collection or projection. The superseded OpenAI execution remains blocked; unrelated untracked V2 files and caches were untouched.

## Next step

Prepare **one bounded local-Ollama nomination execution packet** from the reconciled contexts, pinning the actual configured model/digest, prompt/schema, input/output/context accounting, runtime and source-review ceilings. Do not run it without separate authorization. This should test the nomination handoff inside the existing block pipeline, using the existing retired contexts as development material; it must not inherit the old OpenAI fingerprint, 10/12 criterion or clipped-control claims.

[review-v1.json](review-v1.json) and [preparation-manifest-v1.json](preparation-manifest-v1.json) bind the reconciliation result. General production containment, natural discovery, automated provenance, review throughput, economics, recurrence and pastor-level analysis remain unestablished.
