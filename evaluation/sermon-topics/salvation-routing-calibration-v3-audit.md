# Salvation routing calibration v3 audit

- Packet fingerprint: `79871cce90a529f327cdc8f2c3b7e650210e34b18992d995010f74f54d3cf623`
- Policy version: `salvation-leaf-route-calibration-v3`
- Signal: `salvation_gospel_supporting_or_above_probability`
- Decision: `approve_0.55_with_known_low_score_false_negative`
- Approved boundary: `0.55`
- Routed cached blocks: `126/518` (`24.3%`)
- Route policy active in this packet: `false`

The descending search located the transition region. Both `0.60` probes and the
`0.55`/`0.54` probes contain developed salvation material and warrant the
relationship pack. Both `0.50` probes are primarily narrative setup or practical
discipleship rather than developed salvation relationships. The `0.40` probes
split: one is a genuine salvation question and one is correctly adjacent
spiritual formation.

The approved production boundary is `0.55`. It is preferred to `0.54` because
the probabilities are quantized to hundredths and one strong `0.54` example is
not enough reason to tune the policy to that exact observation. At `0.55`, the
router requests the leaf pack for 126 of 518 eligible blocks. At `0.50`, the
signal is already mixed and would route 139 blocks.

Known limitation: Rusty Williams, video 590, block 26 has only `0.40`
Supporting-or-above probability but clearly discusses who will be in heaven and
what happens to people who never hear the gospel. This remains a frozen
false-negative evaluation fixture. It is not a manual production exception:
another `0.40` block in the same packet is correctly not routed, showing that a
lower threshold cannot recover it without also admitting adjacent formation
material.

The broad score is therefore an inspected cost/recall router, not a complete
salvation detector. The next evaluation concerns whether the independently
cached `salvation-relationships-v1` judgments are useful on routed blocks.
