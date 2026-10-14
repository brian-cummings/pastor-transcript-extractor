# Codex Project Instructions

- Do not run large fixture or corpus reclassification/evaluation jobs.
- Do not monitor long-running classification or evaluation progress.
- While developing, run only focused unit tests and inexpensive static checks.
- Make frequent commits as coherent, reviewable changes are completed; do not accumulate a large batch of uncommitted work. Keep commits focused and preserve unrelated existing changes.
- When a change is ready for dataset validation, give Brian the exact command and let him run it.
- Always provide a CLI tie-in for new workflows, checks, and review packets, using the project's `pte` CLI rather than requiring standalone scripts as the user-facing entry point.
- Assume Brian's virtual environment is already active when providing copy-paste commands. Use `pte` or `python` directly; do not prefix commands with `.venv/bin/` or include venv activation steps.
- Brian's handoff role is to execute commands, approve/reject concrete results, and make minor edits. Prepare the cases, defaults, inputs, and proposed changes for him; do not assign open-ended selection, experimental design, JSON authoring, or annotation work.
- Own interpretation and next-step recommendations after Brian reviews the prepared results. Ask only for decisions that cannot reasonably be resolved from the available evidence, with a concrete proposal ready for approval.
