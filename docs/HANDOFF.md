# Current agent handoff

**2026-11-25: merges done; pool expansion built, Brian's runs pending.** Read
[BENCHMARK_EXPLAINER.md](BENCHMARK_EXPLAINER.md) section 14.
- Merges 158→156 and 88→110 are done without the archive drive. The evaluation migration had left old repo paths in
  2,280 canonical-clip manifests; clips are now found at the migrated location and still hash-checked (`15087e9`).
- The text pre-filter failed v1 (84.8% in top 5 against a 95% bar). v2 ranks only the cross-source voice pool, in
  production and in the check (`fa7329e`). Brian re-runs `pte identity text-prefilter-check`; it stays off unless v2 passes.
- Pool expansion (`8cb0c79`, then video deduplication): every profile run counts, profiles resolve through their merges
  and each video is kept once, from its newest run. The new step is `benchmark-explainer add-pool`.
  Brian's sequence: `backfill --all-attached --dry-run`, `backfill --all-attached`, `add-pool`, then
  `score-added --ceiling-usd <cap>` (paid, about $5), then `church-fit`.
- Still open: 30 exact names for unnamed profiles (profile audit), shadow association of the 13 new benchmark
  videos, and measuring A2.

**2026-11-24 (evening): church fit reading built; benchmark track stopped.** Read
[BENCHMARK_EXPLAINER.md](BENCHMARK_EXPLAINER.md) sections 11 to 13 first.

Where things stand:
- **Benchmark explainer (stopped before ranking).**
  - Jev score: $8.52, plus an added round of $0.59.
  - The sets were corrected and widened. Gibson has 15 solo sermons and Asscherick 9 (the "with DA" book studies were
    dropped). This used `sermon-review --all`, `sermon-decide`, `add-sermons` and `score-added`.
  - A breadth check (`check-traits`) replaced Brian's per-trait marks. The narrow-set traits turned out to be series
    effects.
  - Brian: these traits are not what makes a pastor fit his church. So E2 was not run.
- **Church fit (current track).**
  - Concerns come from Peachtree Hills's 2026 conference questionnaire, which ranks preaching 1st and equipping 2nd:
    wants W1 to W7, avoid A1 (partisan or political) and avoid A2 (Christian nationalism, not yet measured).
  - The concerns file is `<base>/evaluation/church-concerns/peachtree-hills-v1.json`. The command is
    `pte analysis church-fit --concerns <file> --base-dir <base>` (free). Output: `<base>/evaluation/church-fit/peachtree-hills-v1/FIT.md`.
  - The pool resolves merged profiles (`data.canonical_pool`): 46 pool pastors plus the 2 benchmarks, all named.
  - Top: Maurice T. Battle, Jr. (3 sermons), Jonathan Michael (15), Andrew Korp, Mark Waters, Tony Kimbley.
  - The one plausibility check: Denny Grady (Peachtree Hills's pastor) ranks 34; Brian: "probably not wrong."
  - A1 over-matches Gibson's religious-liberty warnings, so avoid concerns need passage reading.
- **Profiles.**
  - Named this session: 97 Maurice T. Battle, Jr.; 108 Paul Carlson; 139 Henry Johnson; 88 and 110 Aaron L Trelfa
    (same person, merge pending); 94 Denny Grady.
  - Brian named 78 Ronald Isreal, 102 Bruce Hehn, 77 Wesley Tuya, 112 Damian Francis, 133 Myron Jenkins and
    140 Jeffrey Skaggs.
  - 193 and 293 (Rodney Herra and Rodney Herra Jr.) are recorded as different speakers.
  - Benchmark profiles: Gibson is 177 (144 redirects to it); Asscherick is 156 (145 redirects to it).
- **Blocked on the archive drive** (`/Volumes/home/SermonExtractorAudio`; the local `normalized.wav` files are
  symlinks). The merges 158→156 and 88→110, then shadow association and confirmation for the 13 new benchmark videos.
  Exact commands: `<base>/evaluation/identity-pending-commands.md`.
- **Open decisions for Brian.** All the counts come from the read-only audit at
  `<base>/evaluation/profile-audit/profile-audit-2026-11-24.md`.
  1. Apply its 30 exact names for unnamed profiles (free).
  2. Pool expansion: 33 named, ready profiles (209 sermons). `pte analysis backfill --all-attached` is free, and the
     backfill must not put a video in two pool profiles. It also needs a new explainer step that adds pool pastors and
     scores them, at about $5 of Jev.
  3. Measure A2 by reading passages.
- **Environment.** `yt-dlp` was upgraded to 2026.11.23 (older versions got 403s). `pte` remembers the last
  `--base-dir`, and a test run once left it at a temp folder. Always pass `--base-dir /Users/briancummings/Documents/PastorSearchData`.

**2026-11-24 — direction: church-to-pastor matching.** The end goal is helping a church find a pastor who fits its
needs; profiles are a means. Read, in order:
1. [PASTOR_FIT_EXPERIMENT.md](PASTOR_FIT_EXPERIMENT.md) sections 12 and 13. Stylometry tells preachers apart, and the
   opt-in `pte identity` text pre-filter is built, with Brian's free check pending. Similarity to a church's other
   preachers is not a fit signal.
2. [BENCHMARK_EXPLAINER.md](BENCHMARK_EXPLAINER.md). The approved concerns framework (want or avoid concerns, observable
   indicators, no labels; Christian nationalism is the first avoid concern) and the benchmark explainer for Ty Gibson and
   David Asscherick. Built; sermon check done; the paid Jev `score` run is next (Brian runs it, $15 ceiling).
The bound-claim pilot and the thought-unit experiment are closed (see their docs). The entries below are history.

---
**2026-11-15 — bound-claim pilot approved; implement it next.**
Read [BOUND_CLAIM_PILOT.md](BOUND_CLAIM_PILOT.md) in full. Implement §9 in the
order of §5 with the tests in §10, committing per step. Do not run any paid
command; hand Brian the exact commands from §11. The product plan now states the
full analytical scope, including public life and political views. The prior
entries below are historical evidence, not next actions.

---

**2026-11-04 — reader-claim admission v1 stopped; product goal remains unmet.**
The new objective attachment authorized a versioned method replacement and fresh
$3/30-attempt allowance. [Method and frozen acceptance](READER_CLAIM_ADMISSION.md)
explain the protection supplied by each retained/replaced check. Initial revision
reuses exact historical correctness and replaces generic presence with a
source-grounded human action/actor/speech-role relation, both at .90.

- A3 and B1 action grounding each returned .95, paired with reused correctness .91
  and .90. No authored replacement descriptions or new correctness answers.
- Worldly-yielding action grounding returned .82, failing its frozen positive
  expectation; original .82 correctness remains withheld. Raw/normalized answers,
  source/candidate state, item path and exact request reconstruct. No demonstrated
  extraction, context, transport or decision defect explains the failure.
- Paid execution stopped immediately. Background and three authored negative
  controls, final validation, ordinary assembly/support and new document delivery
  were not executed. Do not call the two upstream passes product success.
- Additional v281b89–91 and v3973b63–65 coordinates/artifact hashes were frozen before
  the first paid call, with historical exposure disclosed. No new validation
  judgments were generated/opened and no implementation lock was issued.
- A3's historical delivered result remains intact: 23 preserved JSON/Markdown
  artifact hashes verified. Twenty focused tests passed; separate source review
  and acceptance audit are saved. No helpers or semantic retries; one revision.
- New usage: **3 physical paid attempts / $0.000703752 known list-price usage**;
  $0.008257536 full conservative reservations retained, zero missing usage, invoice
  unknown. Unused $2.991742464/27 attempts is not authority to continue after stop.
- Canonical application-base packet:
  `evaluation/reader-claim-admission-v1/plan.json`; one durable `ledger.json`.
  `ACCEPTANCE.md` and `.json` contain failed criteria, source links, receipt traces,
  source review and recommendation. `REPORT.md`/`.json` replay mechanical results.
- Next proposal: one provider-free independent review of the prepared failed
  worldly-yielding source/question/answer, solely to identify a demonstrated
  contract defect with falsifiable repair or confirm method rejection. No new
  provider variant, candidate selection, threshold/model change or release.

Provider-free inspection:

```bash
pte analysis profile-support section-admission-report --plan /Users/briancummings/Documents/PastorSearchData/evaluation/reader-claim-admission-v1/plan.json
```

Implementation commits: `f14120b`, `b298b5a`. Aggregate assistant usage became
unavailable at final verification; exact cross-goal accounting is not claimed.
Verification and handoff followed the hard stop. The older run below remains
historical evidence; its unused allowance is not combined with this one.

---

**2026-11-01 — response-and-conditions bounded run failed acceptance.** Read [product plan](PASTOR_PROFILE_PRODUCT_PLAN.md), [implementation plan](PASTOR_PROFILE_IMPLEMENTATION_PLAN.md), [status](PROFILE_STATUS.json) and AGENTS.md.

Brian wants useful automatic source-grounded analysis plus eventual dimensional comparisons. The current goal is **not achieved**. Preserve historical V8/P1 examples and the older six-clause discussion section; neither establishes general automatic analysis.

- Two evidence-driven semantic revisions ran through the existing shared producer. Final development: 0/10 response proposals qualified. Four unchanged requests/observations/verifier answers were reused exactly, including uncertainty.
- Implementation was locked before the four frozen confirmation outputs. Confirmation: 0/3 response proposals qualified; one incomplete earthquake window appropriately abstained. No tuning followed. All-withheld is measurement failure.
- Actual `pte` source/dimension/assembly/support/document handoffs ran. One local growth-timing discussion clause released after fixing a real multi-block citation-inventory bug; no specific response clause released. This does not meet the two-finding requirement. Original invalid citations and charged attempts remain unchanged.
- 59 focused tests passed. No new recordings, broad jobs, production admission, threshold/model changes or benchmark score.
- New conservative charge: **$0.134451216 of $5**, 38 recorded paid attempts, zero unresolved new usage attempts. Invoice unknown; $4.865548784 unused. Unused credit is not authority for agreement-seeking variants.
- Confirmation remains the original v281b89–91, v3973b63–65, v4589b33–35, v3973b53–55. A 91-manifest metadata audit found prior block-33 exposure in v4589b33–35. Others are not proven unseen. None is called untouched.
- Generated delivery: `/Users/briancummings/Documents/PastorSearchData/evaluation/response-conditions-dimension-v1/DELIVERY_318.md` and `.json`. They link phase assessments, prose, null-valued dimension record, full evidence trace, costs, requirement audit and exact provider-free inspection commands.
- Next concrete proposal: offline audit of the saved verifier questions/state using prepared clear-response, absence and context cases, preserving all original answers and .90 gates. A changed verification meaning/state or another provider experiment requires a specific new frozen decision. Do not launch another prompt/model/schema succession, reopen discovery or hand-author profile prose to fill the gap.
- Assistant aggregate accounting is not fully reconciled across a goal-meter reset and helpers. Meter snapshots and helper estimates are disclosed in the delivery; do not claim exact aggregate remaining credit.

Regenerate/search the configured-base CLI catalog before option lookup. `pte analysis profile-support section-report --plan ... --json` inspects each final assessment without providers. `pte analysis structure-readiness --segment-plan --json` verifies the current document registry. Generated artifacts remain under the configured base; Git retains obsolete planning history.
