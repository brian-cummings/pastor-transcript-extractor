# Codex Project Instructions

- Do not run large fixture or corpus reclassification/evaluation jobs.
- Do not monitor long-running classification or evaluation progress.
- Write generated results, caches, receipts, and other artifacts that are not intended for source control under the application's configured base directory (the same location supplied to `pte --base-dir`), never inside the repository.
- While developing, run only focused unit tests and inexpensive static checks.
- Make frequent commits as coherent, reviewable changes are completed; do not accumulate a large batch of uncommitted work. Keep commits focused and preserve unrelated existing changes.
- Use Markdown and JSON for review and acceptance reports, following the project's existing report format.
- When a change is ready for dataset validation, give Brian the exact command and let him run it.
- Always provide a CLI tie-in for new workflows, checks, and review packets, using the project's `pte` CLI rather than requiring standalone scripts as the user-facing entry point.
- Assume Brian's virtual environment is already active when providing copy-paste commands. Use `pte` or `python` directly; do not prefix commands with `.venv/bin/` or include venv activation steps.
- Brian's handoff role is to execute commands, approve/reject concrete results, and make minor edits. Prepare the cases, defaults, inputs, and proposed changes for him; do not assign open-ended selection, experimental design, JSON authoring, or annotation work.
- Own interpretation and next-step recommendations after Brian reviews the prepared results. Ask only for decisions that cannot reasonably be resolved from the available evidence, with a concrete proposal ready for approval.

## Reuse and responsibility in the evidence pipeline

- Start from a concrete reader-facing statement or behavior. Trace it to the existing category/leaf contract, producer, saved observations and consumer before proposing a new measurement, inference call or pipeline.
- Reuse compatible evidence and established semantics first: materialized observations, individual leaf answers, refinements, previously composed answers and reviewed bound records. A full-pack cache miss, version mismatch or absent field in one artifact is not proof that every reusable constituent is absent. Verify source/context, question meaning, model/provenance, eligibility and applicable policy; do not silently relax compatibility or reinterpret old answers.
- Distinguish an approved design, implemented collector, validated judgment, persisted observation and production admission. Evidence at one stage does not imply the others, and a bounded pilot PASS does not confer broader authority.
- Place a missing semantic distinction at the earliest responsible producer. Support/refutation of a particular point, voiced speaker, preacher adoption and attached qualifications belong in the relevant category-leaf analysis or an existing shared upstream binding component. Reuse those distinctions downstream; do not reconstruct them in profile prose or quotation selection.
- The end-stage pastor profile assembles evidence, aggregates within the declared sample, describes supported patterns/variation, exposes unknowns and selects illustrative examples. It is not a second general-purpose theological extractor or category-leaf classifier.
- Quotation selection starts with an already-supported point and a relevant eligible block: find the most relevant contiguous statement in that block, preserving necessary attribution and qualifications. Code checks literal source location. A quote cannot create a claim, repair missing analytical evidence or change a measurement; existing quotation-execution holds still apply.
- Every consequential gap must name the blocked statement, inspected reuse paths and their outcomes, exact missing information, responsible insertion point, smallest change, acceptance check and applicable authorization boundary. Missing sampling, metadata or presentation is not automatically a new measurement. Leave unsupported statements unknown while delivering the supported feature.
- Keep one active implementation sequence with concrete outputs and exit criteria. Complete the bounded integration/aggregation slice before expanding scope. Do not restart closed discovery/binding experiments, switch models, create another inventory/design loop or add an abstraction merely because a current approach failed; a changed direction must follow a demonstrated gap and the user's authorization.
- Preserve immutable evidence and historical decisions. Do not tune thresholds, meanings, examples or reference readings to make a profile look complete. For an unsuccessful bounded experiment, report the failure and recommend a next action; do not launch a succession of prompt/model/schema variants without a specific user decision.
