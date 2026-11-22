# Thought-unit experiment: do thought-sized units beat time blocks, with the prompt held constant

**Status: specification only (2026-11-22); the Jev boundary design in section 4 comes from offline research. Nothing is implemented and no provider
call is authorized until Brian approves sections 2 to 11.** Read [AGENTS.md](../AGENTS.md), the closed
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

- **Stage 1, boundaries (Jev, new question pack).** Split the whole sermon into units. Section 4.
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

Source of this section: offline reading of the Jev code and arithmetic over the saved leaf table (no provider call); what was read in code is
marked (V), what is inferred (I).

**Precedent.** (V) `validate_boundary_candidate` (`recording_verifier_typesafe.py`) already asks one Noul (probability) question over arbitrary
`before_boundary` and `after_boundary` strings, cached under `boundaries/validations/<hash>.json` by `TypeSafeBlockCache.validate_boundary`.
`NoulLeafPack` is a poor fit because its templates assume one block's `target_text` and block-keyed cache identity. (I) The cleanest route is
a new adapter and cache method patterned on `validate_boundary`, with many candidate pairs batched per request.

**Design (frozen, from three considered).**
- **Chosen: (a) a pairwise continuation question at each candidate sentence end.** "Does the text after this point continue the same thought
  as the text before it?" The answer is the probability of a new thought. The window is 3 sentences on each side, 75 pairs per request (the
  project's constant). Estimated for sermon 281: about 830 to 1,008 candidates, about 14 requests, 250 to 300 thousand input tokens, about
  $0.011 to $0.017 at $0.042 per million.
- **Not chosen: (b) a window Choice ("which sentence starts a new thought, or none").** Cheapest (about $0.005 to $0.008) but a Choice forces
  at most one break per window, overlapping windows can disagree, and a Choice distribution is not a per-boundary probability.
- **Not chosen: (c) coarse-to-fine from the existing blocks.** A block holds about 12 sentences, so block-to-block checks cannot find breaks inside
  blocks, and the free prefilters (saved topic scores, caption pauses) are topic-level or untested. Boundary finding is only about $0.01 to
  $0.02, so tokens are better spent on accuracy here than on a prefilter of unmeasured recall.

**Candidate boundaries.** (V/I) Sentence splitting of this sermon's block texts gives 1,008 sentence ends, median 12 per block, but the ASR
transcript is unreliable: 180 pieces are three words or fewer (rolling-caption duplicates), 24 of 76 blocks end without terminal punctuation
and only 27 of 76 start with a capital. Another sermon in the corpus has about 4 sentence ends in 6,900 words, so sentence splitting fails
outright there. For this experiment: a candidate is a sentence end with at least 4 words on each side. **No text is dropped or edited:** short
fragments stay in the unit text, so every anchor stays literal and locatable by code. Sermons without usable punctuation are out of scope
for this experiment and need a separate fixed-word-window fallback if the approach is ever extended.

**Deterministic chunking rule, constants fixed now and never tuned.**
- A cut at every candidate whose new-thought probability is at least 0.5 (the neutral midpoint).
- Maximum unit size 2,304 characters (the largest existing block): an oversized unit is split at the highest-probability candidate inside it,
  recursively.
- Minimum unit size 2 sentences: a smaller unit merges into the neighbor across the weaker boundary.
- If a cut cannot be mapped to a caption segment boundary, it snaps to the nearest segment boundary inside the same sentence (deterministic).
  Units therefore carry segment indexes and start seconds, which the leaf cache identity and watch links need. Establishing this mapping is
  the first `--check-only` task of the implementation and must succeed before the freeze.

**What this does to stage 2's cost.** (V/I) The 59 leaf questions are replicated per unit and dominate the request: about 19.4 thousand input
tokens per unit regardless of the unit's length, about $0.0008 per unit, matching the pilot's measured 2.48 million tokens over 124 requests.
Unit count therefore drives cost, not boundary finding: about 126 units (8 sentences each) is $0.10, 202 (5 sentences) is $0.16, 336
(3 sentences) is $0.27, against $0.06 for the 76 blocks the pilot already paid.

**Open (unknowable offline).** Jev's accuracy on continuation judgments and whether 0.5 is a meaningful threshold (the pilot never reached
.90 precision on verification); the provider's real per-request question limit and fixed overhead; question-text token calibration; behavior on
very short units. G1 (section 5) is the measurement that answers the first.

## 5. Gate G1 and the other pre-registered measures

**G1 (stops the experiment before stages 2 and 3).** Brian judges 30 positions in the proposed units: 20 chosen boundaries ("does the
text before this point end a complete thought?") and 10 candidate non-boundaries ("should a break have been here?"), picked by a fixed seed
from the source hash. G1 passes when at least 24 of the 30 are judged correct (80%). If it fails, the experiment stops after stage 1 and reports
the failure; no extraction is paid for.

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

- Ceiling for the whole experiment: $3.00 and 600 physical requests. Expected spend is under about $0.60 with Flash: stage 1 about $0.02, stage 2
  about $0.10 to $0.27 (units are priced about $0.0008 each), stage 3 about $0.01 per 10 requests for each arm.
- Worst-case reservations are checked before each stage against the remaining ceiling, as in the pilot.
- No semantic retry, no second prompt, no re-run of any stage to overcome a result, no threshold, rule or leaf-set change after the freeze.
- Stop and report on: G1 failure, stage 3 schema-failure rate over 10% (Flash), transport failures over 5%, ceiling, unresolved usage.
- New ledger, plan and artifacts under `<base>/evaluation/thought-unit-experiment-v1/`. Pilot v1, its leaf table and cache, and the
  object-position check are untouched.

## 8. Reuse and new work

Reused: the saved pilot leaf table and cache (arm B), the existing T/S/P/H questions and `TypeSafeBlockCache` machinery for arm T in a new
cache, the DeepInfra executor and streaming recovery, the ledger, the anchor check, the blind review queue pattern and the report format,
and the seven components. New: the boundary question and cache method (patterned on `validate_boundary`), the unit builder and its segment-boundary mapping and context builder, the (unit, leaf) selector, the stage 3 instruction and runner, and
the arm-blind review queue and report. The shared request-policy module needs one new request version for stage 3.

## 9. What this will not show

Linking one position across units or blocks under different object names is not solved here (arm T may still need an object-grouping
step), nor generalization beyond one exposed sermon, Jev's reliability on other question types, or whether downstream consumers can adopt
a new unit (the cached leaf answers, topic projections and profiles are keyed to the existing blocks).

## 10. Implementation sketch (after approval only)

```bash
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
4. Approve writing the boundary question and the stage 3 instruction for your review before sealing.
5. Confirm this is a separately authorized experiment: `SEGMENT_EVIDENCE_PLAN.md` (line 50) cancelled "another finer target-boundary/source-unit
   redesign" as the next iteration, and this one reopens the unit question on purpose, because the pilot and the object-position check
   demonstrated the gaps in sections 1 and 9.
