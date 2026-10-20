# First read-only segment-backed profile view

**Built and visually checked the first interactive profile preview from existing observations.** It presents reviewed profile 318's three recordings, 158 eligible topic/treatment blocks and 33 routed salvation blocks. There were no model calls, database writes, new measurements, profile-level averages/scores, collection or quote extraction.

[Saved standalone HTML](/Users/briancummings/Documents/PastorSearchData/evaluation/segment-profile-view-v1/e6ceb1da4880695e62b99c930f348b6494901eb60a635b9c14384b05e64154db/index.html). The local browser preview is served on `127.0.0.1:8876`; it is not published or externally hosted.

The view offers:

- Recording filters and four existing high-attention topics per sermon, preserving the existing per-sermon measurement and its meaning. No pooled pastor score is computed.
- Expandable full source segments and recording links at their actual timestamps. These are evidence windows, not selected display quotations.
- Cached treatment probabilities for the same supporting segments.
- All nine approved salvation leaves for each of the 33 measured blocks, with the actual probability, frozen threshold and an explicit observed/below-threshold state. Unrouted targets remain unmeasured; three unresolved leaves remain unavailable. No below-threshold result becomes a pastor's doctrinal denial.
- Visible missing-layer, sampling, attribution and identity limitations. Titles naming John Bradshaw remain source metadata; the reviewed profile currently has no display label.

The renderer loads the sealed inventory and verifies its file hash, all three current source hashes, existing eligibility/ownership gates and current profile membership before presenting evidence. If any changed, it refuses rather than silently regenerating measurements. It escapes all source text, restricts recording links to HTTPS YouTube URLs and includes no remote assets, inference client, editing or persistence controls.

**32 focused tests passed**, including HTML escaping, target/eligibility mismatch rejection, unsupported link rejection, read-only CLI isolation, cache compatibility, closed-path policy and existing command contracts. Browser verification confirmed that the sermon filter hides other recordings and that expanding a supporting segment reveals the source text, timestamp link and matching treatment probabilities. The rendered desktop layout was visually inspected. This is UI verification, not new semantic validation of the cached judgments or a comprehensive accessibility/mobile audit.

```bash
pte analysis structure-readiness --segment-view --check-only --json
```

Without `--check-only`, the command writes only the standalone HTML and sealed view JSON under the configured application base directory. It cannot call a provider or update the database. Quote extraction remains a downstream planned stage; no CENTER/BEFORE/AFTER model request has been prepared or executed.

**Current outcome:** Brian can review an actual source-linked view now. The product remains a bounded sample description, with unsupported theological positions, general recurrence, automatic provenance, broader collection and comparison/scoring unestablished. Further UI feedback can be addressed without reopening the retired exact-span experiments.
