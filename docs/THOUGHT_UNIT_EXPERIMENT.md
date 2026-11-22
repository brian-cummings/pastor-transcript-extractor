# Thought-unit experiment: do thought-sized units beat time blocks, with the prompt held constant

**Status: stages 0 and 1 implemented and committed (2026-11-22); no provider call has been made.** The Jev boundary design in section 4 comes from
offline research. Stage 2 (assessment), stage 3 (main-point extraction), the control arm and the arm-blind review are not built; each waits for the
previous gate and Brian's approval of sections 2 to 11. Brian runs every paid command. Read [AGENTS.md](../AGENTS.md), the closed
[bound-claim pilot](BOUND_CLAIM_PILOT.md) (§15) and the closed [object-position check](OBJECT_POSITION_CHECK.md) (§10) first. This
experiment does not change either result.

## 1. The one question

> Does splitting a sermon into thought-sized units with Jev (instead of fixed time blocks), assessing those units with the existing
> category and leaf questions, and asking an LLM for the main point that supports a flagged leaf, give more accurate and less
> wasteful bound claims than the same steps over the existing time blocks?

Why this. The pilot's block-level claims were 61% (V4 Pro) and 68% (V4.1 Flash) accepted on Brian's labels, and its failures included
a qualification stranded in the neighboring block, a cause and a position split across blocks, and about 10.6 unranked claims per block.
The whole-sermon request in the object-position check returned one excluded line and none of the seven components, so more context was not
the repair. This experiment tests the other hypothesis: the unit's shape (a complete thought) plus conditioning on an assessed leaf.

## 2. Design: one sermon, two arms, three stages

Sermon 281, profile 318, "The American Experiment: Success or Failure?" (source and block texts from pilot v1's saved leaf table, hash
recorded at freeze). The seven pre-registered components and their source spans are the object-position check's `COMPONENTS`, reused
unchanged. Exposure disclosure: those components were written after reading this sermon's pilot claims; this is exposed development
material, not independent validation.

| Arm | Units | Leaf signals | Stage 3 prompt, leaf rule, model |
| --- | --- | --- | --- |
| T (thought units) | Jev-defined thought units (stage 1) | existing T/S/P/H questions on the units (stage 2, new calls) | identical |
| B (time blocks, control) | the 76 existing blocks | the saved leaf table (already paid) | identical |

The control exists so a good result can be attributed: arm B uses the same new prompt, leaf rule and model on the old blocks. Without it,
an improvement could come from the prompt or leaf conditioning and not from the units.

- **Stage 0, wording probe (Jev, development).** Settle the two boundary question wordings on a different sermon. Section 4a.
- **Stage 1, boundaries (Jev, new questions).** Split the whole sermon into units. Section 4.
- **Stage 2, assessment (Jev, existing questions).** Run the existing topic, salvation, public-life treatment and style packs on the
  units, in a separate cache so no pilot artifact is touched. Report routing (section 6).
- **Stage 3, main point (LLM).** For each flagged (unit, leaf) pair, one request asks for the main point of that unit that supports
  that leaf, as a bound-claim record. Both arms.

## 3. Frozen choices (fixed before any output exists)

- **Producer for stage 3: DeepSeek V4.1 Flash, reasoning off, both arms.** It was the pilot's second producer, was not distinguishable from
  V4 Pro on Brian's labels (17 of 25 against 11 of 18), and costs about one eighth as much ($0.061 against $0.489 for 99 blocks). The
  alternative, V4 Pro, needs a ceiling near $8 because worst-case reservations dominate. This is Brian's decision (section 11).
- **Flagged leaves.** Categories for the public-life position question this experiment targets: `P:critical`, `P:supportive`,
  `P:prescriptive`, `P:advocative`, `P:theological`, `P:moral`, on units with `T:society_public_life` at or above 0.9. A pair is flagged when
  the leaf probability is at or above 0.8; at most the top two leaves per unit. Same rule, same numbers, both arms. No other category is
  run. This restricts the test to one position area, as the seven components do.
- **Stage 3 instruction.** One new instruction, `thought-main-point-v1`, sealed by hash at freeze and identical for both arms. It carries
  the five rules the object-position instruction took from Brian's labeled defects (no stories, prayers or recitations as claims;
  self-contained propositions with referents named; scope of "we", "us" and "you" kept; polarity as stance toward the proposition as
  written; qualifications and reasons from the unit and its immediate context) and adds: return only the unit's main point that supports the
  named leaf, or no record. Brian reviews the text before it is sealed.
- **Context.** Each request carries the unit and, for resolving references only, the adjacent units (arm T) or adjacent blocks (arm B), as the
  pilot did. Anchors are located by code in the unit text; context-only anchors fail.

## 4. Stage 1: Jev boundary design

Sources: offline reading of the Jev code and arithmetic over the saved leaf table (no provider call), and the public TypeSafe docs plus the
installed TypeSafe skill (read 2026-11-22). (V) marks what was read in code or docs, (I) what is inferred.

**Precedent.** (V) The TypeSafe "structure recovery" cookbook (docs.typesafe.ai/cookbooks/autoformat.md) is the same problem on a small
scale. Code splits lines and tags them. Pass 1 asks one Noul per adjacent line pair in a single request. Code merges with thresholds
(0.2 after a line without terminal punctuation, 0.5 after one with it). Pass 2 asks one Choice per merged block. The model never
generates text. Its wording lesson applies directly: a "same paragraph" question over-merged (0.61 to 0.72 on list items, 13 blocks) while
"picks up mid-sentence" gave 17. Quoting the lines in the question instructions is deliberate. In our code, (V)
`validate_boundary_candidate` (`recording_verifier_typesafe.py`) already asks one Noul over arbitrary `before_boundary` and
`after_boundary` strings, cached under `boundaries/validations/<hash>.json`; `NoulLeafPack` is a poor fit (single `target_text`, block-keyed
cache identity). The new method is patterned on `validate_boundary`, batching candidate pairs per request.

**Design.** The model gives judgments and code decides, per the TypeSafe skill. Two narrow Noul questions per candidate boundary (and a third, across skipped text, for interjections; see below) replace the
single, vague "continues the same thought" question (the docs warn that Jev "answers the question you wrote, not the one you meant" and
that broad wording over-merges):

- **Q1, mid-sentence.** "Does the second passage pick up mid-sentence from where the first passage stops?" (a syntactic fact).
- **Q2, new point.** "Does the second passage begin a new point, rather than continue, illustrate or answer the point of the first?"

Both passages are quoted in the question instructions (3 sentences on each side), as the cookbook does; no whole-sermon state.
Wording is finalized by stage 0 (section 4a) and then frozen.

**Truth table (every combination has an outcome; thresholds 0.7 and 0.3, the docs' starting values, fixed now and never fitted).**

| Q1 | Q2 | Outcome |
| --- | --- | --- |
| at most 0.3 | at least 0.7 | cut |
| at least 0.7 | any | no cut |
| any | at most 0.3 | no cut |
| any other combination | | unsettled: no cut, counted and reported; the size cap below may still split here |

**Candidate boundaries.** (V/I) Splitting this sermon's block texts on sentence ends gives 1,008 candidates, but the ASR text is
unreliable: 180 pieces are three words or fewer (rolling-caption duplicates), 24 of 76 blocks end without terminal punctuation and only 27
of 76 start with a capital. Another corpus sermon has about 4 sentence ends in 6,900 words. A candidate is a sentence end with at least
4 words on each side. In a stretch with no terminal punctuation longer than 60 words, caption-segment ends become candidates (code tags
them, as in the cookbook). **No text is dropped or edited:** short fragments and duplicates stay in the unit text, so anchors stay literal and
locatable by code. Sermons without usable punctuation are out of scope for this experiment.

**Text used.** (V) The pilot's block `text` (which the saved leaf table holds) is already deduplicated by the project's rolling-caption
normalizer (`caption_normalization.py`, `rolling-caption-v1`): block 93 goes from 228 raw tokens to 82, and the mean deduplication ratio over
the 76 blocks is 0.64. The leaf table text equals that normalized text, not the raw text. Short residual repeats remain at line joins
("wildest dreams.", "religious experiment.") because the normalizer's overlap rule needs 3 or more words (or 2 and at least half of the
shorter side). For candidate generation, code treats a piece that repeats the tail of the preceding piece as part of it. The text itself is
not changed, because every anchor and arm B's saved leaf signals are keyed to it. Sentence splitting reuses the project's `_SENTENCE_END`
(`sermon_topics.py`). For time mapping, each line of a block's text corresponds to one `normalization.normalized_units` entry carrying
`source_segment_indexes` (72 of the 76 blocks align line for line; the other 4 snap to their first segment, deterministically), which
resolves the segment-mapping question.

**Interjections and resumption (look-ahead).** A thought can be interrupted and then resumed. In sermon 281, "And we have to conclude that
the American experiment." is followed by five pieces of aside ("I mean there's no way around it." "Excuse me." "The facts are obvious."
"[clears throat] Sorry." "I'm sorry.") and resumes six pieces later ("We have to conclude ... that the American experiment is working
brilliantly."). Adjacent 3-sentence windows cannot see the resumption, so they would cut before and after the aside and strand the claim from
its lead-in. So for every boundary the truth table marks "cut" or "unsettled", code also asks a third question across the skipped text:

- **Q3, resumption.** "Does the second passage resume the point the first passage left unfinished?" The first passage is the 3 sentences
  before the cut. The second is the 3 sentences that start after each skip of 1 to 8 sentences (a look-ahead limit of 8 sentences, fixed now).
- If Q3 is at least 0.7 at the smallest such skip, the skipped sentences are an aside: the unit is one contiguous span through the resumption,
  the aside's sentence range is recorded and flagged, and no cut is made at either end. Q3 between 0.3 and 0.7 is unsettled (no merge). Q3 at
  most 0.3 at every skip means a real break. An aside longer than 8 sentences is treated as a digression and cut. The limit is stated, not tuned.
- Cost: up to 8 extra questions per flagged cut. Assuming about 300 flagged cuts, about 2,400 questions.

**Chunking rule from the answers, constants fixed now.**
- Cut at every "cut" outcome of the truth table, unless it falls inside an aside merged by Q3.
- Maximum unit size 2,304 characters (the largest existing block): an oversized unit splits at the candidate with the highest Q2 inside it,
  recursively. Minimum unit size 2 sentences: a smaller unit merges into the neighbor across the boundary with the lower Q2.
- If a cut cannot be mapped to a caption segment boundary, it snaps to the nearest segment boundary inside the same sentence
  (deterministic). Units carry segment indexes and start seconds, which the leaf cache identity and watch links need. Establishing the mapping
  is the first `--check-only` task of the implementation and must succeed before the freeze.

**Cost and limits.** (V) Documented limits: 64k tokens per request (state plus all questions), 32k per question, no documented limit on the number of
questions per request (our 75-per-request batch is a project constant set after 150 questions exceeded the budget). Price $0.042 per million
input tokens, output free. Measured on sermon 281 with the implemented candidate rules (937 pieces, 751 candidates): 1,502 first-pass questions (two per candidate), 21
requests, about 416 thousand input tokens, about $0.017. The resumption pass adds up to 8 questions per flagged boundary; if 30% of the candidates
are flagged that is 1,800 questions, 24 requests, about 727 thousand tokens, about $0.031. Stage 1 totals about $0.05, and stage 0 (240 questions, 4
requests) about $0.003. Stage 2 dominates: (V/I) the 59 leaf questions are replicated per unit, about 19.4 thousand input tokens or $0.0008 per unit regardless
of length, matching the pilot's 2.48 million tokens over 124 requests. About 126 units (8 sentences each) is $0.10, 202 (5 sentences) is $0.16,
336 (3 sentences) is $0.27, against $0.06 for the 76 blocks the pilot already paid.

**Model version.** `jev-1.13.0` for every stage and both arms, as in the pilot, so the arms differ only in the unit. `jev-1.14.0` (October 14, 2026,
the current `jev-latest`, same price) lists multilingual support and Box and no boundary changes; it is unexamined here, and the docs advise
sending the version that thresholds were tuned on.

**Open (unknowable offline).** Jev's accuracy on boundary questions in long ASR passages; the provider's real fixed overhead; question-text
token calibration; behavior on very short units. G1 (section 5) is the measurement that answers the first.

### 4a. Stage 0: wording probe (development, before the freeze, not part of the acceptance)

The TypeSafe skill's workflow is to probe wordings on representative cases and compare variants in one request, and the cookbook shows wording
moved the result by four blocks out of seventeen. So, before the plan is frozen:

- Material: 40 candidate boundaries from a different sermon (the lowest video id in the pilot's leaf table other than 281), 20 where code
  finds a sentence end followed by a topic change and 20 where it does not, chosen by a fixed seed from the source hash. Not sermon 281 and
  not used in any acceptance measure.
- Up to three wordings of each question are sent in one request. Development labels for the 40 pairs are Claude's reading, disclosed as such
  (no Brian time). The wording with the highest agreement at the 0.7 and 0.3 thresholds wins, ties to the plainer wording. Thresholds are
  not fitted, and no wording that names specific test items is allowed (the skill's "prompt gymnastics" flag).
- Cost: well under $0.01. The exact payloads and answers are saved, and the winning wordings are frozen into the plan. A second probe round
  is not run.

## 5. Gate G1 and the other pre-registered measures

**G1 (stops the experiment before stages 2 and 3).** Brian judges positions in the proposed units, picked by a fixed seed from the source
hash: 20 chosen boundaries ("does the text before this point end a complete thought?"), 10 candidate non-boundaries ("should a break have
been here?"), and up to 10 detected asides with their resumptions ("is the passage between the two spans an interruption, and does the speaker
resume the same thought?"). G1 passes when at least 24 of the 30 boundary positions are judged correct (80%) and, if any asides were detected,
at least 80% of the judged asides are correct. If it fails, the experiment stops after stage 1 and reports the failure; no extraction is paid for.

**Measures, reported for both arms where they apply.**

1. **Components.** How many of the seven appear among the records, and whether the "working brilliantly" statement carries its
   religious-view qualification (an arm T unit or its record must hold both parts). Pilot baseline, blocks and the old prompt: 6 of 7,
   unqualified.
2. **Precision.** Brian labels a blind, shuffled sample of 30 records per arm (60 in one queue, no arm identity, the pilot's accept and
   reject:field vocabulary including `role`), plus the same seven-component judgments from section 6 of the object-position spec.
3. **Routing (stage 2).** Among all units of an arm, the percentile of the `T:society_public_life` score for the unit or block that holds
   each component. Reported with the saved block baseline (b92 0.96, b93 1.0, b113 0.86).
4. **Volume.** Records per sermon against the pilot's 319.
5. **Efficiency.** Jev and LLM requests, tokens and dollars per stage per arm, and cost per accepted record (all stages counted for arm T;
   arm B counts its stage 3 plus the saved leaf pass for this sermon).

## 6. Acceptance, frozen before execution

The experiment passes only if all of these hold, judged as above:

- **A1 (G1).** At least 80% of the 30 sampled boundary positions correct.
- **A2 (components).** Arm T has at least 6 of the 7 components present and the component 1 qualification attached.
- **A3 (precision).** Arm T's accepted share on its 30 records is at least 0.80 and at least 0.15 above arm B's.
- **A4 (efficiency).** Arm T's cost per accepted record is no more than twice arm B's.

Low power is stated up front: 30 labels per arm cannot resolve differences much smaller than 0.15 to 0.2. A pass is engineering evidence that
the unit shape helps on one exposed sermon, not validation or production admission. If A3 fails with arm T at or below arm B, the unit
shape is not the repair; if arm T beats arm B but misses 0.80, the contract remains the failing component.

## 7. Cost, ceilings and stops

- Ceiling for the whole experiment: $3.00 and 600 physical requests. Expected spend is under about $0.60 with Flash: stage 1 about $0.05, stage 2
  about $0.10 to $0.27 (units are priced about $0.0008 each), stage 0 under $0.01, stage 3 about $0.01 per 10 requests for each arm.
- Worst-case reservations are checked before each stage against the remaining ceiling, as in the pilot.
- No semantic retry, no second prompt, no re-run of any stage to overcome a result, no threshold, rule or leaf-set change after the freeze.
- Stop and report on: G1 failure, stage 3 schema-failure rate over 10% (Flash), transport failures over 5%, ceiling, unresolved usage.
- New ledger, plan and artifacts under `<base>/evaluation/thought-unit-experiment-v1/`. Pilot v1, its leaf table and cache, and the
  object-position check are untouched.

## 8. Reuse and new work

Reused: the saved pilot leaf table and cache (arm B), the existing T/S/P/H questions and `TypeSafeBlockCache` machinery for arm T in a new
cache, the DeepInfra executor and streaming recovery, the ledger, the anchor check, the blind review queue pattern and the report format,
and the seven components. New: the two boundary questions and the cache method (patterned on `validate_boundary`), the unit builder and its segment-boundary mapping and context builder, the (unit, leaf) selector, the stage 3 instruction and runner, and
the arm-blind review queue and report. The shared request-policy module needs one new request version for stage 3.

## 9. What this will not show

Linking one position across units or blocks under different object names is not solved here (arm T may still need an object-grouping
step), nor generalization beyond one exposed sermon, Jev's reliability on other question types, or whether downstream consumers can adopt
a new unit (the cached leaf answers, topic projections and profiles are keyed to the existing blocks).

## 10. Implementation sketch (after approval only)

```bash
pte analysis thought-units probe --base-dir <base> --check-only
pte analysis thought-units segment --base-dir <base> --video 281 --check-only
pte analysis thought-units segment --base-dir <base> --video 281
pte analysis thought-units review-boundaries --base-dir <base>
pte analysis thought-units assess --base-dir <base> --check-only
pte analysis thought-units extract --base-dir <base> --arm t --check-only
pte analysis thought-units review --base-dir <base>
```

Every paid step has `--check-only`. Brian runs the paid commands; offline focused tests only.

## 11. Decisions for Brian

1. Approve the frozen choices (section 3), measures and acceptance (sections 5 and 6), or edit them now. They cannot change after an
   output exists.
2. Producer: Flash (recommended, ceiling $3.00) or Pro (ceiling about $8).
3. Approve the ceiling, the labeling load (30 boundaries and 60 records) and the control arm.
4. Approve writing the two boundary questions (and the stage 0 probe) and the stage 3 instruction for your review before sealing.
5. Confirm this is a separately authorized experiment: `SEGMENT_EVIDENCE_PLAN.md` (line 50) cancelled "another finer target-boundary/source-unit
   redesign" as the next iteration, and this one reopens the unit question on purpose, because the pilot and the object-position check
   demonstrated the gaps in sections 1 and 9.

## 12. Stage 0 and 1 implementation (committed)

Code: `src/pastor_transcript_extractor/thought_units/` (`candidates.py`, `questions.py`, `decide.py`, `jev.py`, `stage.py`) and
`commands/analysis/thought_units.py`; offline tests in `tests/test_thought_units.py`. Jev calls reuse the SDK pattern of
`recording_verifier_typesafe.py` with an immutable answer cache (`answers.json`) and the shared ledger (ceiling $3.00 and 600 attempts, `leaf` step).

```bash
pte analysis thought-units probe-pairs --base-dir /Users/briancummings/Documents/PastorSearchData     # written; no provider call
pte analysis thought-units probe --base-dir /Users/briancummings/Documents/PastorSearchData --check-only
pte analysis thought-units probe --base-dir /Users/briancummings/Documents/PastorSearchData           # Jev, about $0.003
pte analysis thought-units segment --base-dir /Users/briancummings/Documents/PastorSearchData --video 281 --check-only
pte analysis thought-units segment --base-dir /Users/briancummings/Documents/PastorSearchData --video 281
pte analysis thought-units review-boundaries --base-dir /Users/briancummings/Documents/PastorSearchData
```

Stage 0 development labels were written by Claude (`probe_labels.json`, `labeled_by` recorded), not by Brian. 6 of the 40 pairs are ambiguous and left
null; there are 7 true "new point" and 27 false labels, and no true mid-sentence positives (candidates are sentence ends), so the Q1 wording is chosen
only on avoiding false positives. Q3 (resumption) has a single wording and is not probed. Both limits are disclosed; G1 is the real test.
The paid steps need `TYPESAFE_API_KEY` and a clean, committed working tree. The wordings are in `questions.py`; Brian reviews them before the probe runs.

## 13. Result (2026-11-22): G1 FAIL; the experiment stops after stage 1

Brian judged all 40 sampled items. Boundaries Jev cut: 17 of 20 correct. Candidates Jev did not cut: 4 of 10 correct (6 of 10 needed a break).
Boundary and non-boundary positions together: 21 of 30 (70%) against the 80% bar. Detected asides: 0 of 10 correct against the 80% bar. Both parts of
G1 fail, so by section 5 stages 2 and 3, the control arm and the arm-blind review are not run, and nothing was spent on extraction.

Cost: stage 0 $0.0024 and stage 1 about $0.066, $0.0685 of the $3.00 ceiling over 79 requests. Stage 1 cost more than the $0.05 estimate because 67% of
boundaries were flagged for the resumption pass, not the 30% assumed.

Diagnosis from the saved answers (descriptive; the 40 judgments are exposed and are not used to fit anything):
- Precision of Jev's confident cuts is good (17 of 20). Recall is poor: Q2 left 437 of 751 candidates in the 0.3 to 0.7 band, and 435 boundaries were
  "unsettled" and therefore not cut. The 6 missed breaks had Q2 of 0.27 to 0.62 and the 4 correct non-breaks 0.21 to 0.47, so the values overlap and a
  different threshold would not separate them (n is 10).
- The aside mechanism failed. Q3 reached 0.7 on 96 of 4,034 answers (2.4%), 48 of 51 detections came on unsettled boundaries, the median detection value
  was 0.73 (barely over the threshold), 18 of 51 were one-sentence "asides" ("I'll tell you where.", "What shall we do?", "You want to listen to this."),
  and Q3's wording was never probed. Asking 8 skips per boundary and taking the first hit also invites false matches.
- The asides were not needed for the case that motivated them. Rebuilding the units from the saved answers without any asides gives 63 units with the seven
  components still in two units (1 to 4 together, 5 to 7 together), because Q2 left the interjection boundary unsettled, so it was not cut.
- Units are not finer than time blocks: 65 units (median 645 characters, mean 887) against 76 blocks (mean about 760), with a median of 11 pieces.

Acceptance criterion advanced: A1 (G1) evaluated and failed. New evidence: Jev boundary questions of this form are precise but under-cut and the
resumption question over-fires. Justified next action: none inside this experiment. See the closing proposal given to Brian.
