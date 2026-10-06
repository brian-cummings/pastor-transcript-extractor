# Stage 3 topic-boundary audit

## Decision

Keep `topics-v3-mission-discourse-boundary` unchanged. The twelve frozen
whole-sermon packets do not show another reproducible semantic-boundary defect
comparable to the former mission failure.

| Topic | Decision | Finding |
| --- | --- | --- |
| `discipleship_spiritual_formation` | monitor | One plausible one-level overcall, in a projection-ineligible children's story, and a few debatable eligible blocks. Strong scores otherwise track growth, surrender, prayer, spiritual practice, or transformation. |
| `adventist_doctrine_identity` | no issue | Incidental artifacts and institutional references remain at level 1. Every eligible block at level 2 or above develops a distinctive doctrine or denominational identity. |
| `vocation_stewardship_daily_life` | monitor aggregation, not the question | The broad topic routinely receives level-1 probability from everyday language, as designed. Supporting-or-higher probability separates developed evidence from that baseline. |

No topic question changes, cache invalidation, provider calls, or corpus reruns
are warranted.

## Scope and method

This was a read-only adversarial inspection of the twelve packets frozen by
`stage3-whole-sermon-cohort-v1.json`, using their existing
`topics-v3-mission-discourse-boundary` / `jev-1.13.0` observations. The packets
contain 618 blocks, of which 519 pass the existing final-sermon projection
gate. Scores and distributions below are cached model outputs, not estimates
from a new run.

The audit searched the three named topics at their highest scores, at
projection transitions, and around the supplied counterexamples. It also
checked whether high results persisted across semantically different sermons.
This is a boundary audit of a deliberately selected cohort, not a population
error-rate estimate.

## `discipleship_spiritual_formation`

### Strongest evidence for the concern

- Video 4052 block 66 scores 3.09, with 0.79 probability on levels 3-4, for a
  children's-story conclusion about helping someone and making a friend. A
  level near 2 is more defensible: the instruction is lived Christian conduct,
  but formation is not the block's principal subject.
- Video 350 block 59 scores 2.85 for Jean Valjean becoming kind, industrious,
  and generous after receiving kindness. This is a defensible transformation
  illustration, but the score is near the upper edge of what the block alone
  supports.
- Video 4052 block 78 scores 3.03 across a long mixed block containing Dolly
  Parton's charity, Joseph's humility, and direct exhortation to boast in the
  Lord. The formation evidence is real, but block breadth makes the exact
  level debatable.

The clearest case, 4052/66, is already excluded from projection because it is
outside the final sermon and classified as
`childrens_or_religious_education`. It therefore has no sermon- or
pastor-level effect.

### Strongest evidence against a repeatable defect

- Video 4589 blocks 46 and 48 score 3.92 and 3.81 while explicitly developing
  growth over time, prayer, surrender, dying to self, the Holy Spirit, and
  transformed heart, will, and mind.
- Video 3974 blocks 87, 91, and 92 score 3.87, 3.80, and 3.98 while repeatedly
  teaching daily surrender, prayer, resisting sin, and changed habits.
- Video 4052 block 84 scores 3.90 while instructing hearers to pray, read
  Scripture, seek the Spirit, and persist against distraction. Block 112
  scores 3.92 while explicitly applying humility, dependence on God, prayer,
  wisdom, trust, and drawing closer to God.
- Video 1200 block 45 scores 3.50 for time in Scripture and asking God to
  transform the person and form Christlike character.

Across the cohort, 37 eligible blocks score at least 3. The inspected high
blocks overwhelmingly concern formation rather than a generic “Christians
should do X” instruction. The marginal examples are ordinary adjacent-level
ambiguity, not a symmetric or semantically inverted pattern.

### Aggregation impact

The supplied false-positive candidate contributes nothing because it is
projection-ineligible. A small number of eligible one-level overcalls could
slightly raise a sermon's expected-prominence mean, but the sustained episodes
in videos 3974, 4052, and 4589 are genuine and would dominate either proposed
sermon measurement. Retain representative-block links and compare the expected
score with supporting-or-higher probability when interpreting a high profile
value.

## `adventist_doctrine_identity`

### Strongest evidence for the concern

- Video 1200 block 10 mentions distributing *The Great Controversy*. It scores
  1.16 with 0.88 probability on level 1 and is projection-ineligible. That is
  the intended incidental result.
- Video 4430 block 44 mentions Southern Adventist University and *The Desire of
  Ages*. It scores 0.93 with 0.85 probability on level 1 despite being
  projection-eligible.
- Video 590 block 12 names Chattanooga First Seventh-day Adventist Church in a
  service greeting. It scores 0.93 with 0.93 probability on level 1 and is
  projection-ineligible.

These are the strongest contextual/artifact cases found, and none is promoted
to developed evidence.

### Strongest evidence against a defect

- Video 1200 block 39 scores 2.84 while contrasting Sunday sacredness with the
  Sabbath and immediate-at-death heaven with resurrection from the grave.
- Video 4052 block 82 scores 2.72 and explicitly describes Seventh-day
  Adventists as watchmen and lightbearers entrusted with the three angels'
  messages.
- Video 590 block 51 scores 2.68 while discussing Karen Seventh-day Adventists,
  reception of the seventh-day Sabbath, and an Adventist congregation.
- Video 4458 block 73 scores 2.54 for the unconscious state of the dead,
  resurrection, and rejection of purgatory. Videos 4312 and 4317 supply further
  developed state-of-the-dead, Sabbath, sanctuary, judgment, remnant, and
  millennium evidence.
- Video 4430 block 50 is the closest institutional case above level 2. Its 2.15
  score is reasonable because the preacher develops what growing up entirely
  inside an “Adventist everything” social world meant for his identity; it is
  not a passing institution name.

Only twelve eligible blocks score at least 2, none scores at least 3, and all
twelve contain actual doctrine or denominational self-understanding. The
requested artifact/context boundary is already present.

### Aggregation impact

Incidental institutional references contribute a small amount to normalized
expected prominence but almost no supporting-or-higher mass. Developed
distinctives remain sparse and traceable to evidence blocks. No special
aggregation correction is indicated beyond preserving both measurements and
their evidence links.

## `vocation_stewardship_daily_life`

### Strongest evidence for the concern

- Video 1200 block 9 says only that Vacation Bible School was fun. It scores
  0.58, with 0.56 probability on level 1, and is projection-ineligible.
- Among the 519 eligible blocks, 142 have level 1 as the modal vocation result;
  178 have an expected score above 0.5, while only 23 have at least 0.50
  probability on supporting-or-higher. The mean expected score is 0.503, but
  the mean supporting-or-higher probability is only 0.069.
- Ordinary illustrations routinely mention money, work, schedules, meals,
  education, possessions, or decisions. Those words legitimately create some
  incidental probability under this intentionally broad topic, even when the
  sermon is about something else.

This confirms a level-1 baseline, but not a semantic inversion.

### Strongest evidence against changing the question

- Video 4052 blocks 75 and 77 score 2.96 and 3.29 while the blocks are dominated
  by poverty, education, work, career decisions, earnings, and professional
  development. These are direct members of the stated category even though
  they occur inside a biographical illustration.
- Video 590 blocks 61 and 62 score 2.56 and 2.99 while developing a church
  construction failure, costly mistakes, contracting, budgets, and a plan to
  complete the project. Again, the daily-life/stewardship subject is real.
- The largest obvious administrative contaminations are already excluded:
  video 4394 blocks 16-18 concern a school bill, salary pledge, and offering;
  video 1033 block 12 concerns hiring painters; and video 590 block 69 contains
  event logistics.

Only one eligible block scores at least 3 and ten score at least 2. Tightening
the question to suppress incidental anecdotes risks erasing legitimate work,
money, education, planning, and responsibility evidence that the broad topic
was created to retain.

### Aggregation impact

This is where the observed baseline matters. Pastor-level aggregation must not
interpret `mean_normalized_expected_prominence` by itself as developed-topic
prevalence: level-1 probability is intentionally included in that expectation.
Use `mean_supporting_or_above_probability` as the primary developed-emphasis
measurement, retain normalized expected prominence as a secondary sensitivity
measure, aggregate with equal-sermon weighting, and keep representative blocks
visible. No new inference or cache structure is needed for that policy.

## Regression and rerun decision

No fix is warranted, so there is no proposed wording or rerun scope. Preserve
the three supplied blocks as named monitoring cases in future broad-pack
reviews:

- 4052/66: generic Christian service exhortation versus formation;
- 1200/10: Adventist artifact mention versus identity/doctrine;
- 1200/9: incidental daily-life language in excluded service material.

If future independent sermons reproduce an eligible discipleship overcall on
blocks that contain only moral or practical exhortation and no growth,
practice, transformation, obedience-as-discipleship, or formation discourse,
that would justify reopening the question. A single adjacent-level
disagreement does not.
