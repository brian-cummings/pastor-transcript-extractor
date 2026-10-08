# TypeSafe topic Stage 4 stability audit

## Evidence

- Evaluated report: `stage4-topic-stability-v1.json`
- Report SHA-256: `4e1ec6fe0e460f27d55d574dabce99d1e4f968b96a1488a4b97aa3c5c3fdc9bd`
- Report input fingerprint: `7f693aec7881336c710b610a6019fd8688390e1f4c04e606dbe1c6847ddc9366`
- Readiness fingerprint: `3b8763eea4ecce4c1830a9a29351873ced29d4b7ef8b977635b24de85e190122`
- Question pack: `topics-v3-mission-discourse-boundary`
- Cohort: twelve reviewed sermons, three each for four pastors; three declared
  series and two declared periods per pastor.

The report uses equal-sermon means. Its primary measure is probability mass at
Supporting or above; normalized expected prominence remains a sensitivity
measure. No TypeSafe request was made by the evaluator. It materialized and
reused the already-reviewed cached block observations through the generic
immutable sermon-analysis cache.

## Findings

The broad observations are useful for sermon discovery and conditional routing.
They do not support pastor-to-pastor comparison from this cohort.

Several developed themes remain visible when any one sermon is removed. Examples
include David P Ryder's Scripture evidence (mean `0.323`, leave-one-out maximum
delta `0.046`); Rusty Williams's God, salvation, sin, and ethics evidence (means
`0.338`-`0.542`, deltas `0.044`-`0.088`); Ron Clouzet's God, Jesus, and
discipleship evidence (means `0.227`-`0.367`, deltas `0.004`-`0.014`); and John
Bradshaw's sin and ethics evidence (means `0.319` and `0.442`, deltas `0.027`
and `0.040`). These are examples of repeatable broad signals, not a calibrated
acceptance band.

The largest shifts are semantically coherent sermon-specific subjects rather
than evidence of a general classification failure:

- Ron Clouzet video 1037 carries eschatology probability `0.705`, while videos
  4430 and 350 are approximately `0.011` and `0.000`.
- John Bradshaw video 281 carries public-life probability `0.700`, while videos
  4589 and 3973 are approximately `0.006` and `0.038`.
- John Bradshaw video 4589 carries spiritual-conflict probability `0.419`, while
  videos 281 and 3973 are approximately `0.014` and `0.004`.

Those spikes are desirable for finding sermons about a subject. Averaging them
into a stable personal trait would erase the distinction the topic layer is
supposed to preserve.

## Limits

Each declared series contains only one selected sermon, so the reported maximum
between-series delta is the sermon range; it cannot separate a series effect
from ordinary sermon-to-sermon variation. Each pastor also has only three
sermons across two periods, leaving one period represented by a single sermon.
The cohort therefore cannot calibrate a universal stability threshold or a
pastor-comparison policy.

Low means with low deltas may simply indicate repeated absence. They are not
evidence that a pastor rejects or neglects a topic. Conversely, one high sermon
is evidence that the sermon develops a topic, not that the topic characterizes
the pastor.

## Decision

Approve `topics-v3-mission-discourse-boundary` for these bounded downstream
uses:

1. locating representative or counterevidence blocks inside a sermon;
2. sermon-level topic discovery and filtering with the denominator and evidence
   links visible; and
3. routing an eligible cached block into a separately versioned leaf pack.

Do not enable pastor comparison, ranking, theological-stance inference, or an
automatic stability label. Keep the Stage 4 report status
`diagnostic_only_threshold_not_calibrated` and `comparative_use_allowed=false`.

Before the first salvation-relationship leaf request, prepare a bounded routing
packet from projection-eligible cached blocks. It must show the broad
`salvation_gospel` distribution, the proposed deterministic route decision, and
the exact target/context. Review clear routes, clear non-routes, and borderline
cases without changing or rerunning the broad pack. The routed leaf pack must
have an independent question version and cache identity.
