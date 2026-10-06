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

Inspect the packet Markdown, the prepared notes, and every proposed correction.
Only then finalize with the reviewer identity and `--accept-as-reviewed`, or edit
the draft before finalization if a proposal is rejected.

The proposals deliberately make no provider calls. Their SHA-256 hashes and the
source packet fingerprint are preserved in the draft and finalized review.
