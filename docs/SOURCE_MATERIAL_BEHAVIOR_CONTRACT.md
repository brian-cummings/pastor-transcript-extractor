# Source/material behavior contract V1

Status: **PASS — V1 question validation is complete and frozen**, accepted by
Brian on 2026-10-13. Eligibility-only routing is accepted. Broader collection
remains inactive and production thresholds are not established.

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
quotation, and context-boundary decisions. All 23 authored probes matched their proposed labels in the reviewed V1 result.
Natural cases retain raw probabilities rather than acquiring synthetic gold labels.

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

## Completed V1 validation

The [stage-gate PASS](../evaluation/sermon-topics/source-material-stage-gate-v1.md)
is bound to reviewed V1 fingerprint
`0cec4f832c1b0488a2d53406887423484d1d23ae6785ab27bee8fca5383c285e`
and frozen question digest
`5fb1d587af3244deca135e0f40a6c930a96936b075c41491b34871b782f81dcd`.
All 23 authored probes match; twelve natural cases and five excluded content
controls complete the bounded review. Original JSON/Markdown and per-leaf
probabilities/provenance are preserved. No V2, display tuning, overlap suppression,
or larger validation cohort is required.

Retain `4430:36 historical_example=.63` as a legitimate below-display boundary
observation on historical material as presented. At 4430:57 personal testimony
(.70), reported testimony (.88), and quotation (.88) legitimately coexist.
At 4430:37 the quotation (.80) and reported testimony (.76) describe the supplied
narration; the film/story ambiguity remains explicit. These answers do not
independently verify actual historical events or lived experience. The explicit
fictional-Mendoza probe stays negative, supporting the stated fictional boundary
without proving recognition of fiction absent an explicit target/context cue.

Material use does not establish endorsement, factual accuracy, theological
agreement, or denominational identity. The unchanged .70 cutoff is display-only.
Eligibility-only coverage routing is accepted; reassess strict current final
projection eligibility when collecting. Topics remain sampling/diagnostic signals.
Unmeasured blocks are missing evidence, not source-negative observations.

To reproduce or repair the provider-free completion pair from the repository root:

```bash
.venv/bin/pte analysis source-material-stage-gate
```

This command reads only frozen reviewed evidence and reuses exact output pairs;
it never calls a provider or opens the database. The historical
`source-material-review` command remains a bounded development tool, not the
completion command and not a required rerun. All four planned enrichment sets
have completed question validation. Define a concrete downstream use and its
separate collection/projection contract before broader collection; do not add
another leaf taxonomy automatically.
