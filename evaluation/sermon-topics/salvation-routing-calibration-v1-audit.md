# Salvation routing calibration v1 audit

- Packet fingerprint: `3a296603f3500f780440f675b2cf9c0daf9065648ee3e358dc258ccbc4563f15`
- Policy version: `salvation-leaf-route-calibration-v1`
- Signal: `salvation_gospel_supporting_or_above_probability`
- Proposed boundary: `0.70`
- Decision: `boundary_rejected_signal_retained`
- Route policy active: `false`

The cached broad salvation signal is suitable for deciding whether a block should
receive a separate salvation-relationships leaf request. The four strongest
examples contain developed salvation content, and the four incidental examples
do not warrant a leaf request. This validates the signal and the broad pack's
extreme strata without authorizing any provider calls.

The proposed `0.70` boundary is too high. Both sampled blocks immediately below
it are genuine leaf candidates:

- John Bradshaw, video 4589, block 32 (`0.69`) develops surrender to Jesus,
  deliverance from sin, and the practices through which Christ continues his
  work in a believer.
- Rusty Williams, video 590, block 39 (`0.67`) develops judgment, salvation of
  people without explicit gospel knowledge, God's fairness, and entrance into
  the kingdom.

These are false non-routes under the v1 proposal, not evidence that the broad
question or routing signal is defective. The next bounded proposal is `0.65`,
which includes both reviewed false non-routes while leaving the lower,
semantically mixed band unapproved. A v2 packet should therefore contain only
the two closest unused blocks on either side of `0.65`; the eight clear v1
anchors do not need to be reviewed again.

No salvation leaf pack has been run, and no routing threshold is active. The v1
JSON and Markdown are immutable review evidence for the v2 policy identity.
