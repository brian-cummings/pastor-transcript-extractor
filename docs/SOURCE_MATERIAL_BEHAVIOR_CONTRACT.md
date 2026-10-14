# Source/material behavior contract V1

Status: candidate prepared for bounded validation. No question readiness,
production collection threshold, or broader collection is granted.

The question is: what source or material carries the preacher's point in this
block? Six independent leaves cover biblical narrative, personal testimony,
reported testimony, extra-biblical historical example, quotation, and explicitly
identified denominational source. Personal and reported testimony are separate
because whose experience is presented is directly observable and useful.
Quotation is a form dimension and can overlap with source dimensions. The pack
measures material use, including quoted material examined or rejected by the
preacher; it does not measure endorsement or affiliation.

A biblical story must develop an event; a verse citation or doctrine alone does
not qualify. Testimony involves lived faith, spiritual struggle, or perceived
divine action; ordinary autobiography and imagined cases are excluded. Historical
examples require an identifiable extra-biblical episode. Quotation requires
attributed words or a clear quotation frame; indirect reports and familiar
unattributed wording are excluded. Denominational attribution must be explicit,
including an identifiable writer, publication, or institutional source. Mentioning
a denomination as the subject does not mean using its source material.

Only the target supplies material. Context may resolve who "she" is in a target
quotation or who "he" is in a target story, but context-only sources do not count.
The 23 authored probes provide positive, negative, overlap, attribution, rejected
quotation, and context-boundary decisions. These are proposed interpretations,
not measured provider answers.

Route all blocks with strict current final projection eligibility; topic scores
and sampling cues never gate measurement. Natural review samples at most four
eligible blocks from each of videos 1200, 590, and 4430. Cues only diversify that
sample. This bounded sample cannot estimate corpus recall or workload. Question
readiness and coverage routing need separate review.

Use the shared leaf registry, provider adapter, per-block cache, preparation,
refinement composition, and JSON/Markdown output writer. Full source semantics
have a new version and digest. Frozen listener, public-life, and salvation
questions remain unchanged. Routing, display cutoff, and batch composition do
not enter raw source-answer identity. Later revisions should use the shared
leaf-refinement composition to request only changed questions and preserve
unchanged answers and provenance.

## Bounded validation handoff

From the repository root Brian runs:

```bash
.venv/bin/pte analysis source-material-review --prepare-only
.venv/bin/pte analysis source-material-review
```

Preparation reads cached broad observations and current projection eligibility,
writing the complete proposed cases without a provider request. Evaluation
prepares those same bounded inputs and requests only source/material answers
missing from the independent cache. The pinned default model is `jev-1.13.0`.
At most 35 blocks and 210 independent questions are included. Outputs default to
`evaluation/sermon-topics/source-material-review-v1.json` and adjacent Markdown.
Repeated evaluation reuses answers; an unchanged output pair is reused and a
broken companion is repaired. Execution counts are printed for each invocation.

Review raw probabilities and target attribution, rather than demanding exact
label agreement at the unchanged .70 provisional display cutoff. Natural cases
have no authored gold labels. Recommend readiness only after interpreting these
results; revise only a failed semantic boundary if needed. Broader collection
remains inactive. Brian executes the bounded command; Codex interprets the result
and recommends acceptance or a narrow revision.
