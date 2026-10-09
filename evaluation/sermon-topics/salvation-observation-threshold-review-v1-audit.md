# Salvation observation threshold v1 audit

- Packet fingerprint: `eb4c603a011e018791fc031d8d602851c6977fd06cae5cc1ae55a49253b9e166`
- Leaf pack: `salvation-relationships-v2-evidence-boundaries`
- Candidate global threshold: `0.70`
- Decision: `global_threshold_rejected`
- Ordinary reclassification activation: `false`

The packet rejects a single global observation threshold. At `0.70`, the leaf
retention rates are too uneven to assume that equal probability values represent
equal evidence strength across independently worded Noul questions. In particular,
`obedience_as_consequence_or_evidence` would produce no observations despite a
defensible positive at `0.62`. Assurance, divine grace, and final destiny also
contain credible positives below `0.70`.

The result does not invalidate the frozen questions or their cached raw
probabilities. Several leaves show a useful boundary at `0.70`, including
atonement, forgiveness, justification, conversion, sanctification, repentance,
and obedience as a condition or means. Those boundaries are provisionally settled
at `0.70` and should not receive more prompt tuning.

The next review is restricted to five ambiguous leaves:

- `divine_grace_initiative`: compare `0.65` and `0.70`.
- `judgment_final_destiny`: compare `0.65` and `0.70`.
- `faith_as_receiving_response`: compare `0.65` and `0.70`.
- `assurance_security`: compare `0.55`, `0.60`, `0.65`, and `0.70`.
- `obedience_as_consequence_or_evidence`: compare `0.55`, `0.60`, `0.65`, and
  `0.70`.

Calibration remains a deterministic collection policy over persisted evidence.
It must not rerun TypeSafe, change the frozen questions, discard sub-threshold raw
probabilities, or activate production collection before review.
