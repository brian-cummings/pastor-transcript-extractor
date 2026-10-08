# Salvation routing calibration v2 audit

- Packet fingerprint: `530364ff1050793f8f42303ca7110552f87551b36fab2b00c1c924abb4e7dcce`
- Policy version: `salvation-leaf-route-calibration-v2`
- Signal: `salvation_gospel_supporting_or_above_probability`
- Proposed boundary: `0.65`
- Decision: `boundary_rejected_signal_retained`
- Route policy active: `false`

All four boundary cases warrant a salvation-relationships leaf request:

- Ron Clouzet, video 1037, block 58 (`0.65`) develops salvation as human
  destiny, obtaining salvation through Jesus, and the danger of failing to
  realize it through spiritual sleep.
- John Bradshaw, video 3973, block 77 (`0.66`) develops gospel rejection,
  coming to Jesus, believing and being saved, and Christ's final acceptance or
  rejection of the lukewarm.
- Rusty Williams, video 590, block 43 (`0.64`) develops God's saving activity
  among people who have not heard of him, their possible destruction, eternity
  in human hearts, and the Abrahamic blessing reaching every family.
- Ron Clouzet, video 1037, block 21 (`0.64`) develops saved and lost destiny,
  rejects predestination, presents God's plan to save everyone, and explains
  final settlement on one side or the other.

The two cases immediately below `0.65` are false non-routes, so v2 does not
calibrate an acceptable boundary. Lowering from `0.70` to `0.65` would increase
routing only from 94 to 101 of 518 eligible blocks, but cost alone cannot make a
boundary correct.

The next packet should not propose another boundary in five-point increments.
It should perform one cached descending search with two deterministic cases near
each of `0.60`, `0.55`, `0.50`, and `0.40`, plus route-count projections for
each level. This locates the first genuinely mixed or non-route region without
repeating already-reviewed cases or calling TypeSafe.

No salvation leaf pack has been run, and no routing threshold is active. The v2
JSON and Markdown remain immutable review evidence for the v3 search identity.
