# E1a: run one command, then review prepared edits

Codex owns case selection, preparation, technical defaults, provenance, interpretation and the next-step recommendation. Brian runs the command and approves/rejects specific edits, with minor text corrections when needed.

From `/Users/briancummings/code/pastor-transcript-extractor`, run:

```bash
.venv/bin/python -m pastor_transcript_extractor.analytical_caption_review \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

A local browser page opens with up to six short caption edits. For each card:

1. Open **Listen to this clip** and listen to the indicated excerpt.
2. Click **👍 Matches audio**, **👎 Keep original**, or **Can’t tell**. If the proposal is almost right, make a minor edit and approve it.
3. When the page says **Review saved. You’re done**, tell Codex: **“caption review finished.”**

Decisions save automatically. You can stop with Ctrl-C and run the same command later to resume. There are no run IDs to choose, JSON files to edit, thresholds to set, or follow-up evaluation commands to assemble. If preparation fails or finds no suitable cases, send the printed output to Codex; Codex owns resolving it.

Codex will read the saved result at:

`/Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a-caption-screen/report.json`

## What the command does

It starts with the review's known run 145 when its saved source is available, then selects another source using a fixed ordering. It inspects at most six saved sources, prepares at most three nonoverlapping excerpts per selected sermon, and limits each excerpt to 20 seconds. Existing caption normalization supplies **proposals**, never ground truth. Every decision retains the original excerpt and its source/run provenance; accepted edits do not change production transcripts or the database.

This is the first, bounded caption-counterexample screen within E1a. Approvals apply only to the displayed excerpts. They do not assert that a whole sermon, pastor identity, alignment accuracy or a population error bound has been reviewed. Codex interprets the result and prepares the next concrete check or repair. E1b certification remains separate.

The earlier export/freeze/whole-sermon JSON workflow is a low-level engineering facility, not Brian's assignment. Do not use the superseded manual handoff.
