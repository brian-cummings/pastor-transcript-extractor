# Benchmark explainer: what makes a benchmark pastor distinctive, and who else shares it

**Status: specification (2026-11-24). Nothing built or run. Brian approves section 9 before any code or spend.**

## 1. Where this fits

The goal is helping a church find a pastor who fits its needs (Brian, 2026-11-24). Brian approved the
**concerns framework** (2026-11-24) as the way needs are expressed:

- A church states **concerns**. Each has a name, a direction (**want** or **avoid**), an importance (deal-breaker,
  weighted, or nice to know) and **observable indicators**, each with *counts when* and *does not count when*.
- The system never applies a label (no "Christian nationalist", party or ideology; product plan). It reports,
  per indicator, what the pastor said: quotes, in how many sermons examined, stance, and whether it was the
  pastor's own view. "Not found in N sermons" is reported as exactly that, never as absence of the view.
- Concerns come from a vetted **library** (each with indicators and a small test set) or are **custom**
  (a church describes one in plain words; indicators are drafted and the church approves them).
- An avoid concern's instances are always surfaced for a person to review, never averaged away.
- First library concern (later step): avoid Christian nationalism. Indicators: (1) teaches the nation has a
  special covenant or divine status as a Christian nation; (2) calls for law or government to enforce Christian
  belief or practice, or to restrict other faiths; (3) equates faithfulness with a party or candidate, or casts
  political opponents as enemies of God; (4) frames Christian political dominance as a goal. Does not count:
  criticizing or warning against these (including Adventist warnings against church-state union), quoting them to
  refute them, praying for leaders, encouraging voting, defending religious liberty for all.

**Benchmark pastors** are a shortcut to *want* concerns. A church says "we like Ty Gibson"; the system shows
what is distinctive and stable about him, the church confirms which of those it actually likes, and those become
weighted concerns used to rank candidates, with evidence per dimension. This spec builds and tests that shortcut
for two benchmarks Brian named: **Ty Gibson** (pastor 65, speaker profile 144) and **David Asscherick** (pastor 66,
profile 145).

Evidence that shapes the design (`PASTOR_FIT_EXPERIMENT.md` section 12):

- How a pastor talks (stylometry) identifies the person but is not a trait a church wants.
- Overall similarity to a church's other preachers did not predict anything.

So the explainer compares **interpretable dimensions one at a time**, never overall similarity, which is also what
the product plan requires.

## 2. The questions

1. **Explain:** for each benchmark, which dimensions are both **distinctive** (far from the other pastors) and
   **stable** (true in both halves of his own sermons), with evidence passages? Does Brian recognize them as true of him?
2. **Rank:** for dimensions Brian picks from the explanation, does ranking the other pastors give a shortlist
   whose evidence supports "similar on these dimensions"?

## 3. Data (counted read-only, 2026-11-24)

- **Benchmarks:** Gibson has 23 target videos with an extraction, Asscherick 25. Their speaker profiles are
  `unprofiled` (no analysis runs), so they were not in the 47.
- **Comparison pool:** the 47 analyzed profiles (293 sermons), as in the pastor fit experiment.
- **Saved Jev answers:** topic projections exist for only 12 videos, plus the pilot and public-life sets.
  Most blocks need new Jev scoring.

## 4. Steps and techniques

| # | Step | Technique | Cost |
| --- | --- | --- | --- |
| 1 | **Benchmark sermon check:** flag target videos that may not be the benchmark preaching (guests, panels) | Stylometry from the pastor fit experiment: each sermon against the rest of that benchmark's sermons and the 47 profiles. A sermon whose own benchmark ranks outside its top 5 is flagged. Brian keeps or drops each flagged sermon (a list, yes or no) | Free, local |
| 2 | **Free dimensions** per sermon | Existing analyzers run in memory on the extraction windows, without writing to profiles: Scripture use (`sermon-basics` v4: references per 1,000 words, text engagement, Old Testament share), structure (first-person singular and plural, second-person rate, lexical diversity), and sermon length | Free, local |
| 3 | **Jev dimensions** per one-minute block | Existing packs through the existing block builder, cache and transport (reusing every saved answer): T topics (20) on every block; H style, L listener directives (9) and M source material (6) on every block; S salvation (12) and P public life (8) on blocks at the product route (topic at least 0.55) | About $7 to $10 (section 6) |
| 4 | **Pastor values** | Per pastor, each Jev dimension is the **share of their blocks at or above the frozen 0.8 floor** (topics: share at or above 0.55), with the number of blocks as denominator. Free dimensions are the mean over sermons. Probabilities are never used as scores | Free |
| 5 | **Distinctive and stable** | Robust z against the other 48 pastors (median, 1.4826 × MAD). Distinctive: \|z\| at least 1.5. Stable: both halves of the benchmark's sermons (the fixed hash split) have \|z\| at least 1.0 on the same side. Dimensions with fewer than 30 blocks of opportunity, or where the pool's MAD is 0, are reported as "not enough evidence" | Free |
| 6 | **Explanation** per benchmark | Up to 10 distinctive, stable dimensions, largest \|z\| first, each with the pastor's value, the pool median, and 2 evidence passages (the blocks with the highest answer, from different sermons, shown as transcript text) | Free |
| 7 | **Brian's review of the explanation** | Interactive, one dimension at a time: *true of him / not true / can't tell* | About 20 items |
| 8 | **Ranking** | Brian picks 2 to 5 dimensions per benchmark from his "true" list. Pastors are ranked by mean absolute z difference on those dimensions. The top 5 are shown with per-dimension values and one evidence passage each | Free |
| 9 | **Brian's review of the ranking** | Per shortlisted pastor: *the evidence supports "similar on these dimensions" / doesn't* | 10 items |

## 5. Pass marks (fixed before anything runs)

| Check | Pass |
| --- | --- |
| E1 Explanation | For each benchmark, at least 75% of the dimensions Brian can judge are marked *true*, and at most 1 is *not true* |
| E2 Ranking | For each benchmark, at least 4 of the 5 shortlisted pastors are marked *supported* |
| Descriptive only | Whether Gibson and Asscherick are nearer each other than the median pair on the union of their stable dimensions (they ministered together; reported, not a gate) |

Readings:
- **E1 and E2 pass:** the benchmark shortcut works for these two, and the next step is to wire it to the concerns framework.
- **E1 fails:** the dimensions don't capture what makes a preacher recognizable. Report which kinds of dimension failed (topic, style, directive, Scripture) and stop.
- **E2 fails while E1 passes:** the dimensions are right, but the pool or the distance is not. Report and stop.
- No threshold, floor or dimension list changes after results; any second attempt needs a demonstrated defect and Brian's decision.

## 6. Cost, ceilings and stops

- Jev cost per block from the section 31 ledgers (`THOUGHT_UNIT_EXPERIMENT.md`), actual list price: H about $0.00005,
  L $0.00015, M $0.00011, S and P about $0.00015 on routed blocks; T similar to L. About $0.0005 per block for all
  packs. Roughly 340 sermons of about 40 minutes gives about 13,600 blocks, about **$7 actual**. Saved answers
  are reused, so the real cost is lower.
- **Proposed per-run ceiling: $15 and an attempt ceiling set from `--check-only`** (request count plus 6). One run.
  Transport retries are bounded, a rate stop requires at least two failures (`exceeds_failure_rate`), and no semantic
  retry is made.
- About 1 to 2 hours of wall time; Brian runs it under `caffeinate`.
- Everything else is free and local.

## 7. What this will not show

- That a church will like the shortlisted pastors. Brian's judgment stands in for a church's here.
- Anything about positions or deal-breakers. That is the concerns step (Christian nationalism first), which
  needs the LLM stage on retrieved passages.
- Generalization beyond two benchmarks and 47 pastors, most of them from one denomination.
- Stability over time: sermons have no dates.

## 8. Reuse and new work

Reused: the Jev packs, block builder, cache and transport (`bound_claims/leaf_pass.py`), the ledger with
ceilings (`bound_claims/common.py`), the sermon-basics and structure analyzers, and the pastor fit text loading,
caption normalization, split and stylometry. New: a runner over the benchmark and pool sermons with its own
ledger, the value and distinctiveness computation, the explanation and ranking writers, and the two review
loops. CLI: `pte analysis benchmark-explainer census | sermon-check | sermon-review | score
[--check-only] | explain | review | rank | report`. Outputs go to
`<base>/evaluation/benchmark-explainer-v1/`. Implementation waits until the identity pre-filter work is merged,
because both reuse `pastor_fit`.

## 9. Decisions for Brian

1. Approve the design, the pass marks and the Jev spend: about $7 to $10 expected, **$15 ceiling**, one run.
2. Approve the review load: about 2 to 10 flagged sermons (step 1), about 20 dimension judgments (step 7) and
   10 ranking judgments (step 9).
3. Confirm that the comparison pool is the 47 analyzed pastors. Adding the other 271 registry profiles needs
   their sermons analyzed first, which is a separate decision.

## 10. Approval and implementation (2026-11-24; Brian: "ok proceed"; fixed before any result exists)

Approved: section 9 as written. That is the design and pass marks, a Jev spend of about $7 to $10 under a **$15 ceiling** for one run, the
review load, and the 47 analyzed pastors as the pool. Code: `src/pastor_transcript_extractor/benchmark_explainer/`; tests:
`tests/test_benchmark_explainer.py`. CLI: `pte analysis benchmark-explainer census | sermon-check | sermon-review |
score [--check-only] | explain | review | rank | report`.

Details fixed here:

- **Blocks:** none of the benchmark sermons and only 11 of the 293 pool sermons have a saved topic analysis, so blocks are
  rebuilt from each extraction's saved classifier blocks (the final pass, labeled sermon; median 89 seconds). The rule is
  the one the thought-unit experiment verified (`public_set.sermon_blocks`, `arms.transcript_blocks`), giving
  12,138 blocks in all. Saved Jev answers are copied in only when their whole identity matches (`arms.seed_from_pilot`) from
  the extraction's own inference cache and the public-life set caches. The new cache is `<out>/cache/v<video>`.
- **Dollar ceiling:** each request reserves its worst case (65,536 input tokens) before dispatch, and the ledger refuses any
  reservation that would pass $15. The whole-run worst case (about $45 if every block missed and routed) is far above
  real usage (about a tenth), so it is reported, not required to fit up front. The attempt ceiling is the census's
  worst-case requests plus 6.
- **Failures:** a failed pack call is recorded and the run continues. The run stops if failed calls exceed 5% (at least two;
  `exceeds_failure_rate`). A sermon with any failed call is not saved. One resume is allowed (two invocations in all), which
  is the bounded retry. Uncommitted source changes block the paid run.
- **Routing:** T, H, L and M on every block; S where `T:salvation_gospel` is at least 0.55; P where `T:society_public_life`
  is at least 0.55. In values, blocks off the route count as below the floor.
- **Free dimensions:** computed in memory on caption-normalized units (Scripture detection with the production detector,
  pronoun rates, MATTR, length). Nothing is written to the database.
- **Sermon check:** stylometry over the 300 most frequent words. A benchmark sermon is flagged when its own benchmark's
  other sermons rank worse than 5th of 48 candidates.
- **Scale fallback:** where the pool's MAD is 0 (common for rare leaves), the scale is 1.2533 × the mean absolute deviation
  from the median. If that is 0 too, the dimension is "not enough evidence".

## 11. Run status (2026-11-24)

- `sermon-check` (Brian): video 4249 (Gibson) left out, with no sermon window (the recording verifier rejected it as a
  multi-speaker program). The remaining 47 benchmark sermons (Gibson 22, Asscherick 25) all rank their own pastor first
  (median rank 1 of 48), with 0 flagged, so `sermon-review` has nothing to do. Free measures computed for all 340 sermons
  without error.
- `score --check-only` ran more than 10 minutes (it rebuilds about 12,100 block contexts and checks 6 packs against 3
  caches) and was stopped at Brian's request. Estimate from a 3-sermon sample and the section 31 ledgers: about
  10,800 requests (worst case about 14,100), **about $6 to $7 actual**, under the $15 per-request ceiling. Expect about
  15 to 20 minutes of counting and seeding before the first request, then 1 to 1.5 hours.
- Next (Brian): `caffeinate -i pte analysis benchmark-explainer score --base-dir <base>`, then `explain`, `review`, `rank`, `report`.
- `score` (Brian, 2026-11-24): complete in one invocation. 340 sermons, 12,090 blocks, 10,677 requests, 0 failed calls,
  0 incomplete sermons, **$8.52** against the $15 ceiling (above the $6 to $7 estimate, within the approved $7 to $10).
- `explain` (free): Gibson 6 distinctive, stable dimensions (3 not stable); Asscherick 7 (1 not stable).
- **Defect found before review: the benchmark sermon sets are not him preaching.** Of Gibson's 22 recordings, only 5
  are titled as his alone (4243, 4244, 4260, 4264, 4268). 11 are panels with Asscherick and Grasso, 3 are Asscherick solo
  (4259, 4265, 4266), 2 are Rosario solo (4261, 4262) and 1 is a ministry year-in-review (4258). His evidence shows it:
  a "give" passage is Asscherick's donation ad, and a doctrine passage comes from an Asscherick sermon. All 25 of
  Asscherick's recordings are co-hosted Ellen White book studies (`DA with DA`, `COL with DA`), so "denominational
  source" and "80-minute length" describe the format. Step 1 missed this because it compares each recording with the
  benchmark's other recordings, which share the same channel and mix, so the check was circular.
- Review is paused until Brian decides how to fix the benchmark sermon sets.
- **Fix approved (Brian, 2026-11-24: A to D).** `sermon-review --all` lists every benchmark recording with a proposal from
  the speakers its title names (Enter accepts). Gibson keeps 4243, 4244, 4260, 4264 and 4268. 4243 and 4244 name no
  speaker; both are single-voice and their wording is nearest Gibson's titled solo recordings (style distance 1.81 and 2.23,
  against 1.94 and 2.52 for Asscherick's DWELL solos; the same check puts every titled solo with its own speaker). The
  year-in-review video (4258) has no speaker in its title, so it is dropped by hand. Asscherick keeps all 25, and his
  explanation describes his co-hosted book-study series. Pass marks and dimension list are unchanged; no new Jev calls.
- **Revised (Brian, 2026-11-24: option 1).** Asscherick's own preaching is the 3 DWELL sermons filed under Gibson's channel
  (4259, 4265, 4266), now filed under him with `sermon-decide --decision file:66`. His 25 book studies are dropped
  (not preaching). Final sets: Gibson 5 (halves 3 and 2), Asscherick 3 (halves 2 and 1, so his results are thin). Re-run
  `explain` (free): 10 dimensions each. The pre-fix explanation is kept as `EXPLAINER.before-sermon-fix.md`.
  Caveat for the readings: each set is essentially one or two series (Gibson: *The End* and DWELL; Asscherick: DWELL), so
  topic dimensions can reflect the series as much as the preacher. Both "Asks listeners to: give" passages are Light
  Bearers donation inserts. `review` now shows and opens each evidence passage on YouTube.
- `review` (Brian): 20 of 20 dimensions marked true (Gibson 10, Asscherick 10), so **E1 passes for both**. Caveat for the
  readings: the sets are small and series-bound, so E1 confirms that the named traits are recognizable, not that
  they are typical across his whole preaching. `rank` now shows each trait's direction (MORE or LESS than most) and opens
  the shortlist examples.

## 12. Widening the benchmark sets (Brian, 2026-11-24: option A)

The sets above are one or two series each, so the explanation shows what is unusual about those series. Brian adds
chosen recordings one at a time:

1. `pte source add '<watch URL>' --target-pastor <ty-gibson | david-asscherick>` (prints the new source id), then
   `pte run --source-id <id>`: intake, captions or transcription, and extraction.
2. `pte analysis benchmark-explainer add-sermons` (free): appends benchmark recordings extracted since `sermon-check`,
   measures the free dimensions and runs the sermon check against the reviewed sets. The pool is fixed; the step refuses
   if it changed.
3. `sermon-review --all`: only undecided recordings are asked (earlier decisions stand).
4. `score-added [--check-only] [--ceiling-usd 2.00]` (Jev): scores kept sermons without signals in its own round
   under `added-rounds/round-<n>/`, with its own plan, ledger and per-request dollar ceiling, and one resume. The approved
   $15 run's files are never touched. About $0.0007 per block (section 11), so about $0.04 per sermon.
5. `explain`, `review` (only new dimensions are asked; marks are about the pastor, so they carry over), `rank`, `report`.

A speaker-profile basis (benchmarks as profiles 144 and 145, filled by the identity workflow) is the reusable design;
those profiles are currently empty placeholders, so it is deferred until the benchmark idea passes.
- **Widened sets (2026-11-24).** Brian added 16 single recordings (19 requested; 2 never discovered, 1 had no sermon
  window) and kept all 16 in `sermon-review`. The sermon check now compares against the reviewed sets: 15 of 16 ranked
  their own pastor first, and 4629 was flagged (rank 18) but kept. `score-added` round 1: 637 requests, 0 failures,
  **$0.59** (cap $2). Sets: Gibson 15 (halves 8 and 7), Asscherick 9 (halves 5 and 4).
- `explain` on the wider sets (the narrow-set version is kept as `EXPLAINER.narrow-sets.md`):
  - **Gibson:** 9 dimensions. 4 carried over (public life illustrative, critical and supportive; Adventist identity). 5 are
    new: obedience as consequence or evidence, justification, denominational sources, longer sermons, less discipleship.
    The prophecy and politics dimensions from *The End* dropped out or became unstable, so they were series effects.
  - **Asscherick:** 4 dimensions (Adventist identity; faith as receiving; give, still DWELL donation inserts; and the new
    creation and origins). 7 of his narrow-set dimensions dropped out.
  - **Reading:** Brian marked all 20 narrow-set dimensions true, yet most of them turned out to be series effects. So
    the narrow-set E1 pass is weak evidence, and the verdict should come from the widened sets. Marks on carried-over
    dimensions stand; only new dimensions are asked.
- **E1 replaced at Brian's request (2026-11-24):** "you probably don't need my judgement". A short clip cannot show a
  pattern, so the per-dimension mark became two checks, fixed before they were computed. (1) **Breadth**
  (`check-traits`, free): on his side of the typical pastor in at least half of his sermons, and for a MORE dimension
  counted in blocks his top 3 sermons hold at most 60% of the hits. (2) **Content** (Claude reads up to 6 top passages
  per MORE dimension): does the measure count what its definition says? Brian's earlier marks are kept but no longer
  gate anything.
  - **Gibson, 4 of 9 pass breadth:**
    - Obedience as consequence or evidence: 10 of 15 sermons, top 3 hold 56%. Content about 4 of 6 on target (grace
      first, changed life follows), with one passage a critique of merit theology and one ambiguous.
    - Denominational sources: 11 of 15, 57%. Content 5 of 6 are Ellen White quotations.
    - Less discipleship: 15 of 15.
    - Longer sermons: 14 of 15.
    - Failed: public life illustrative, critical and supportive (4 to 5 sermons, mostly *The End*), justification
      (2 sermons), and Adventist identity (top 3 hold 60.5%, just over).
  - **Asscherick, 0 of 4 pass.** With 9 sermons each trait sits in 3 to 6 of them, so his set is not yet characterized.
- **Benchmark track stopped before ranking (2026-11-24).** Brian: "I'm questioning whether these particular traits
  are what would make a pastor a good fit for our church." Finding: starting from a liked pastor yields what is
  measurably unusual about him (sermon length, Ellen White quotations, less discipleship talk), which mostly is not
  what a church chooses on. E2 was not run. The work moves to the concerns framework, using the church's own
  questionnaire. Draft: `<base>/evaluation/church-concerns/peachtree-hills-v1-draft.md`.
