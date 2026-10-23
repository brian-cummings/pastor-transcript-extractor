# Pastor profile: current workflow

**Current as of 2026-10-23: V8 is the generated review profile for profile 318.** The [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md) defines the experience; the [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md) defines completed work and the delivered P1 portability case.

## Reproduce the current example

```bash
pte analysis structure-readiness --segment-view --description --json
```

Verify current source/membership/cache compatibility without writing artifacts:

```bash
pte analysis structure-readiness --segment-view --description --check-only --json
```

The generation command writes `index.html`, `profile-v8.md`, `description-v8.json`, `review-v8.json` and the existing `next-capability-v2.md/json` beneath the configured app base in `evaluation/pastor-profile-description-v8/<manifest>/`. The source/implementation manifest identifies the immutable output directory. Check-only and generation share the description fingerprint; check-only returns no artifact path.

These default commands reproduce the prepared profile 318 case. P1 adds one explicit prepared selection:

```bash
pte analysis structure-readiness --segment-view --description --profile-id 130 --json
pte analysis structure-readiness --segment-view --description --profile-id 130 --check-only --json
```

Other explicit profile IDs are rejected. Profile 130 uses only recordings 1037 / 350 / 4430 from the prior bounded inventory, not its full membership. It reuses existing assembly and rendering. Its apparent adopted theological center and pastoral posture remain unknown; four style descriptions and three cross-point interpretations were manually authored by Codex, pending Brian’s acceptance.

Open the [profile 130 HTML](/Users/briancummings/Documents/PastorSearchData/evaluation/pastor-profile-portability-p1/b71806632436ea3eff9f5df37d10edd3ca232ca2875ea7de76d79673efe97a67/index.html), [readable Markdown](/Users/briancummings/Documents/PastorSearchData/evaluation/pastor-profile-portability-p1/b71806632436ea3eff9f5df37d10edd3ca232ca2875ea7de76d79673efe97a67/profile-p1.md), [artifact review](/Users/briancummings/Documents/PastorSearchData/evaluation/pastor-profile-portability-p1/b71806632436ea3eff9f5df37d10edd3ca232ca2875ea7de76d79673efe97a67/artifact-review-p1.md) or [consequential gaps](/Users/briancummings/Documents/PastorSearchData/evaluation/pastor-profile-portability-p1/b71806632436ea3eff9f5df37d10edd3ca232ca2875ea7de76d79673efe97a67/consequential-gaps-p1.md). Companion JSON files preserve the evidence, authoring inputs and per-path reuse outcomes. All generated artifacts remain under the configured app base. The final description fingerprint is `f33f0ab5d9eff2144f129986aa89fa9b008b4138b3908a76d061e00f1a778e40`.

Normally Brian runs dataset validation. A specific instruction may authorize Codex to execute a small bounded run; V6–V8 were generated under such instructions. Neither command calls a provider, fills caches, changes measurements, writes the database or collects data.

## What V8 contains

The 163-word opening connects existing evidence into seven explicit authored interpretations: overall impression, apparent theological center, preaching approach, potential strength, pastoral posture, noticeable sample emphasis and a question for further examination. Each interpretation has:

- Exact supporting reviewed-point identities and full-point digests.
- A rationale, limits, alternative explanation and interpretation kind/status.
- Links through the original reviewed descriptions and bindings to observations and source passages.
- Independent withholding if required support is changed, missing or incompatible.

`profile_portrait.py` and `data/profile-portrait-authored-v1.json` provide this bounded composition. The four style descriptions and ten local readings remain intact. The original 29 reader descriptions plus seven interpretations give 36 reader claims; the same 53 example sets and eight gaps remain. Portrait interpretations use the reviewed-point ledger rather than entering measurement/example selection as independently observed findings.

The at-a-glance table, per-recording accounts, complete reviewed frames/qualifications, full source windows and technical provenance remain below the portrait. Authored paraphrases/merged accounts use `profile-reader-editorial-v2.json`; earlier authored inputs remain preserved.

## Read the result at its declared authority

The portrait is provisional, with reader acceptance pending. “Center” describes an apparent organizing thread of reviewed material, not measured predominance. The detailed theological readings came from assurance-focused development and may bias the apparent center. A possible strength is not measured audience effectiveness; the review question is not diagnosed contradiction. No benchmark, ministry stability, school label or calibrated score is established.

Compatible inputs and valid links do not prove semantic correctness. The saved V8 `portrait-review-v1.md/json` records manual comparison of the authored warrants with the reviewed inputs; it is not independent validation of every upstream judgment. No visual browser layout review was performed.

Current description fingerprint: `0b6f4d0cedaf64a0f4cfc2958c3101e8605823c5090e845a43fcbea2daed8545`.
Current manifest: `b1f0bd2b0830157196e722586daaed08aca87c84bc0fbc949d758685c2b928a5`.

## Next step and historical workflows

The old D1–D4 goal is complete. The separately authorized P1 case is delivered and artifact-reviewed, with automatic reuse, manual interpretation and missing upstream meaning disclosed. Stop after this case and its report. Brian’s concrete reader acceptance remains pending; no further case, semantic expansion or model experiment is active.

The [Ollama synthesis experiments](PASTOR_PROFILE_SYNTHESIS.md) are closed diagnostic history. Do not run them as the default next step. Their rejected outputs remain preserved alongside all earlier profile versions. [Historical snapshots](PASTOR_PROFILE_HISTORY.md) preserve earlier workflow descriptions; their command examples do not override current holds.
