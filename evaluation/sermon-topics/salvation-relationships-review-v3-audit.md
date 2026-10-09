# Salvation relationships v3 audit

- Packet fingerprint: `97f260ed11119684e4ff39f81c1661e489f24f5c548ec34e2d3c485532357c6c`
- Leaf pack: `salvation-relationships-v2-evidence-boundaries`
- Route threshold: `0.55`
- Decision: `out_of_sample_review_accepted`
- Ordinary reclassification activation: `false`

The held-out packet excluded all twelve v2 development cases while keeping the
questions and route unchanged. The leaf pack continued to distinguish different
salvation relationships rather than raising every related leaf together. Strong
examples separated grace and forgiveness, sanctification and repentance, and a
broad closing gospel appeal in ways consistent with their target texts.

Three scores remain useful observations rather than prompt-tuning targets:

- Ron Clouzet video 4430 block 27 tests whether sanctification intentionally
  includes deliverance from sin's power.
- David P Ryder video 1200 block 44 tests the boundary between surrender and
  repentance related to a saving benefit.
- John Bradshaw video 3973 block 81 tests whether general righteousness language
  establishes justification or right standing.

None warrants changing the frozen questions. The revised evidence boundaries
kept the debatable judgments moderate, and further tuning against individual
examples would risk overfitting.

The broad router also behaved as intended. David P Ryder video 4458 block 66
routed at `0.58`, while every specialized leaf remained at or below `0.36`.
The route therefore favors recall without forcing a positive theological
observation.

The leaf questions and route are frozen. The next decision is a code-owned
collection threshold over the preserved raw probabilities. A provider-free
boundary packet should test a candidate `0.70` threshold by comparing, for every
leaf, the closest reviewed judgment below it with the closest reviewed judgment
at or above it. No production collection should activate until that boundary is
reviewed.
