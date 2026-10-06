# TypeSafe Topic Stage 2 Review Proposals

These proposal files are deterministic, human-reviewable inputs for the protected
topic adjudication workflow. Each proposal is bound to one exact prospective packet
fingerprint. It pre-fills suggested corrections and notes, but it does not mark any
review check complete and never changes cached TypeSafe observations.

Create a draft beside a packet with:

```bash
pte analysis topic-review-draft \
  /path/to/topic-prospective-sanity-sampler-v1.json \
  --proposal docs/review-proposals/typesafe-topic-stage2/VIDEO_ID.json
```

Inspect the generated draft Markdown. It includes the prepared notes, every proposed
correction, an interpretation guide, and the complete cached packet evidence needed
to judge it. Only then finalize with the reviewer identity and
`--accept-as-reviewed`. If a proposal is rejected, report the video, block, topic,
and preferred interpretation so the draft can be revised before finalization.

The proposals deliberately make no provider calls. Their SHA-256 hashes and the
source packet fingerprint are preserved in the draft and finalized review.
