# Implementation plan for the Astra analytical review

Prepared September 11, 2026 from `REVIEW.md`, with spot checks of current implementation. This is a proposed implementation sequence, not a claim that validation has passed. No dataset jobs were run. Existing unrelated working-tree changes are outside this plan.

The next milestone is to determine whether a small set of literal Scripture measurements supports useful comparison across independent sermon series. Preserve evidence-linked sample descriptions throughout. Treat a supported negative result as completion of the milestone.

## Most impactful findings, in priority order

| Priority | Finding | Why it changes the roadmap |
|---|---|---|
| 1 | Transcript representation can change the measurements themselves. Run 145 contains repeated rolling captions and three recorded mentions of the repeated Romans 3:24 phrase. | Potentially affects counts, denominators, recurrence, lexical features and timing together. Audit paired original/reviewed sermons before tuning distances or expanding features. One inspected sermon establishes a mechanism, not its corpus prevalence. |
| 2 | Current stability diagnostics do not establish pastor-level reliability. LOO aggregate variance is not sermon variance; minimum-depth cohorts are not matched-depth learning curves. | For an ordinary mean at five sermons, LOO variance is 16 times smaller than sermon variance. Correct the interpretation immediately; do not apply that correction factor to nonlinear ratios. |
| 3 | The sampling design cannot separate pastor effects from series, source and time. Snapshot has no dated sermons and only two multi-source profiles. | More sermons from the same source/series can make bias more precise. Reviewed metadata and independent series are required; code alone cannot resolve this. |
| 4 | Comparison has concrete false-closeness and comparability failure modes. Constant-panel coordinates disappear; missing coordinates change the geometry by reference; inputs can be stale. | These are bounded correctness fixes worth doing before validation. They cannot, by themselves, certify similarity. |
| 5 | Bootstrap duplicates fabricate independent-sermon recurrence. | Two different sermons with zero shared-book similarity can produce similarity one when a resample repeats one sermon. Existing recurrence intervals need an explicit unsupported status until replaced. |
| 6 | Feature expansion has little evidential support yet. The best two Scripture candidates have conditional interval widths around the population IQR; structure has one profile; semantic historical fixtures validate a different analyzer version. | Start with detected citation density and detected Bible-text span fraction. Defer broader style/ranking investment until the existing signals survive review. |

## Implementation sequence

### 1. Correct the measurement and eligibility contract

Scope: `comparison_features.py`, `population_analysis.py`, relevant CLI/report consumers, and documentation.

- Separate feature purpose (description, diagnostic, experimental comparison) from validation status. Existing `core` membership and 5/8-sermon gates must not imply certification. Initially no dimension is certified.
- Describe `scripture_text_engagement_fraction` as **detected Bible-text span fraction**. Change display labels first; preserve historical keys. Introduce a versioned new key only if measurement semantics change.
- Move accepted alignment score and anchored alignment fraction to diagnostic-only in the new comparison policy. Keep descriptive outputs. Defer unstable breadth/concentration/recurrence families from the initial certification pilot.
- Rename the misleading between/within ratio as between-profile variance relative to aggregate deletion variance, or remove it from reliability recommendations. Retain LOO deltas as deletion sensitivity.
- Expose actual within-profile sermon distributions for the two primary candidates, identifying equal-sermon versus pooled-word estimands explicitly. Do not silently substitute one for the other.
- Rename minimum-sermon summaries to cohort summaries. Suppress claims that their trend validates a depth threshold.
- Mark current recurrence bootstrap intervals unsupported for independent-sermon recurrence. Do not repair this by merely deduplicating resamples and leaving their variable depth unexplained.
- Version changed policies/reports; keep old snapshots readable with their historical meanings. Update CLI consumers of the old variance fields together.

Acceptance: small synthetic tests demonstrate the LOO distinction, cohort semantics, diagnostic exclusions and unsupported recurrence intervals. No current report presents exploratory eligibility as empirical certification.

### 2. Repair comparison correctness and input provenance

Scope: `benchmark.py`, `style_profile_analysis.py`, fingerprint helpers in `profile_analysis.py` / `sermon_analysis.py`, and storage access where needed.

- Require exact-current input fingerprints for current comparisons and style aggregates. Reuse Scripture profile aggregation's preparation/fingerprint lookup pattern. Validate source, extraction boundaries, membership and analyzer/model configuration as applicable.
- Support explicitly pinned historical inputs as a separate declared mode. Never automatically recompute stale inputs as a side effect of reporting.
- Choose a single supported feature mask across the candidate and eligible reference set before computing any distances; freeze family weights and expose exclusions. Abstain when required support is absent.
- For constant calibration coordinates, expose the raw difference and explicit unscalable/out-of-panel status. A nonzero candidate difference cannot disappear into a zero-distance closeness claim. A completely unusable mask yields abstention.
- Separate frozen calibration population from panel membership and declare treatment of candidate overlap. Freeze comparison scope rather than switching features and panel silently at sermon eight.
- Preserve raw differences, omitted coordinates, effective weights and capped-distance flags. Treat numerical ties as ties; ID sorting may organize output but must not assert a unique winner.
- Keep any remaining distance/rank output explicitly experimental. Withhold certified nearest/close language until Step 5; do not invent uncertainty bounds before the experiment exists.

Acceptance: focused tests cover stale source and membership, historical pinning, constant-panel mismatch, all-unusable features, unequal missingness, ties and fixed comparison scope. Existing historical snapshots remain reproducible under their recorded policy.

### 3a. E1a: targeted falsification with prepared, approval-only review

**Division of responsibility:** Codex chooses and prepares the cases, sets documented defaults, preserves evidence, interprets the results and proposes the next bounded action. Brian executes commands, approves/rejects concrete outputs and makes minor corrections. Do not hand Brian sampling design, run-ID selection, JSON editing, threshold selection or open-ended labeling work.

The initial deliverable is a small **caption-excerpt screen**, not a request to fully annotate multiple sermons:

- One command (`python -m pastor_transcript_extractor.analytical_caption_review`) reads existing saved Scripture runs, with no migration, backfill, alignment evaluation or semantic inference. It opens a local review page and resumes saved decisions on rerun.
- Start with run 145 when its original source still matches the saved hash. Select another source through a fixed hash ordering, record skipped inputs, and inspect at most six source artifacts. No inference of actual transcript method or pastor identity follows from source IDs.
- Prepare at most three nonoverlapping, ≤20-second candidate edits per selected sermon, using existing caption normalization only as a proposal. Freeze original snippets, saved citation evidence, source hashes, policy and code provenance before the reviewer sees the cards.
- Present original captions, proposed text, surrounding context and a timestamped video link. Brian clicks Matches audio / Keep original / Can't tell, or makes a minor edit and approves. No decision is pre-approved. Saves are automatic and prior decisions remain in the event history.
- Recompute citation counts on both versions of an approved **excerpt** with the same local detector context. Report only excerpt-level counterexamples, rejected proposals and uncertainty; never extrapolate them to full-sermon density, alignment accuracy, recall or population error rates. Every report says whole-sermon review and feature certification have not occurred.
- Codex reads the report and owns the next bounded check or repair proposal. If the screen has no useful candidates, Codex investigates its recorded exclusions; Brian is not asked to repair packets or select substitutes.

See `E1A-HANDOFF.md` for Brian's single command and review instructions. Original transcripts and production records remain unchanged.

The earlier `analytical_pilot.py` export/freeze/evaluate functions remain engineering facilities for a genuinely reviewed whole-sermon paired audit. They are not the default user handoff and must not consume excerpt approvals as whole-sermon annotations. Any later full-sermon paired-shift experiment must be prepared by Codex and must disclose the additional ground truth it needs; do not recreate the previous open-ended manual assignment. The full-audit .25-IQR falsification bound and E1b distributional gates are not applied to excerpt changes.

Acceptance: focused tests verify deterministic bounded case preparation, source drift handling, short nonoverlapping edits, approval-only changes, preserved originals, automatic save/resume, rejected/unclear cases, and refusal to infer certification. Browser verification exercises a minor edit, approval, rejection and completion using synthetic snippets. Brian runs the actual bounded screen.

### 3b. E1b: reviewed measurement-error certification pilot

Proceed only for worthwhile candidates after E1a failures have been repaired or bounded. Reuse the packet format, but freeze a **new** certification manifest; do not retroactively treat targeted E1a cases as a representative sample. Disclose reused development cases and include independent verification cases for repairs.

- Expand to 12 sermons from six reviewed pastors, two each, spanning caption methods and low/high measurements; double-review four and adjudicate differences.
- Freeze verified identity, sermon dates, series, passage/topic, source and actual transcript method, eligible/included/excluded decisions, original/reviewed hashes, reviewer provenance, intended domain and practical tolerances.
- Extend the shared runner with reviewed text-span/translation audits, event and span accuracy, paired signed/absolute shifts, median and 90th-percentile shifts, subgroup checks and uncertainty clustered by sermon/pastor. Separate representation, window and translation changes.
- Proposed gates from the review: median absolute shift ≤.10 frozen IQR, 90th percentile ≤.25 IQR, no reviewed subgroup bias >.20 IQR, episode precision ≥.95 and recall ≥.85. Freeze tolerances before execution; wide intervals produce **inconclusive**, not pass.
- These gates certify only a bounded measurement-error claim for the pilot domain. Pastor comparison still requires E2.

The E1b evaluator, uncertainty estimation, independent reviews and span/translation accuracy checks are deliberately deferred pending E1a findings. No current command implements or claims E1b certification. Twelve sermons remain a pilot minimum, not a power calculation or a guarantee of a pass.

### 4. Repair analytical text only where E1 shows material bias

Scope: `sermon_analysis.py`, `caption_normalization.py`, `profile_analysis.py`, and affected structure preparation.

- Validate the existing caption normalizer as a candidate against reviewed audio/text; do not assume prompt normalization is measurement ground truth.
- If needed, add an analytical text/citation-episode representation that retains source mappings and legitimate repetition. Keep original and revised measurements side by side in the pilot.
- Define whether each numerator and denominator counts transcript tokens, analytical tokens, detected spans or distinct spoken episodes. Test overlapping spans and repeated captions explicitly.
- Version analyzer semantics and fingerprints. Revalidate affected measures on the paired material; do not backfill the corpus automatically.

Acceptance: targeted caption/citation/span tests plus E1 evidence show the affected candidate meets the frozen error bounds. If not, revise again, narrow scope or stop that feature. More data is justified only for identified uncertain strata.

### 5. Implement E2 only for E1b survivors

Extend the offline manifest-driven runner; keep it separate from routine population snapshots.

- Audit coverage of the nine existing profiles with ≥10 sermons. Target eight pastors ×12 sermons, four from each of at least three series across at least two dated periods. Count missing strata before collecting anything.
- Compare matched depths within the same pastors, disjoint samples and held-out series/periods. Track original-sermon identity across every resample. Pairwise recurrence estimators must exclude self-origin pairs; use explicit fixed-exposure designs for richness.
- Separate actual sermon variation from measurement uncertainty. Fit variance models only when the design supports the requested components; emit non-identifiability reasons for rank-deficient/confounded designs.
- Evaluate the actual candidate transforms and distances, including CLR smoothing and family weighting if composition survives. Raw-share stability is not validation of CLR geometry.
- Freeze common masks and panel/calibration policies. Perturb candidate and reference samples independently; test series/source deletion, panel additions/deletions, and fixed versus refitted scales.
- Report raw pair differences and uncertainty, repeatability by depth, same-pastor versus different-pastor concordance, selection frequencies, uncertainty sets, margin intervals and abstention rates. Treat pairs as dependent observations.

Proposed gates from the review: dimension reliability ≥.80 with lower bound ≥.70; practically meaningful pair difference outside the preregistered negligible zone; family concordance ≥.80 with lower bound >.65. A named nearest reference additionally requires ≥.80 resampling selection, ≥.80 retention under prespecified nonwinner-panel perturbations, and a margin interval above a meaningful gap. Absolute closeness needs its own calibration. Freeze the numerical practical-difference thresholds before execution.

Acceptance: synthetic fixtures demonstrate same-origin exclusion, fixed-depth sampling, held-out-series separation, reproducible seeds/masks, rank-deficient abstention and panel sensitivity. Brian executes dataset validation. Eight pastors may still produce an inconclusive result; this is not a deployment-sized validation claim.

### 6. Deliver the bounded report; conditionally revisit structure/style

- Deliver sample descriptions immediately under their literal scope. After E2, add only validated dimensions with coverage, sermon distributions, raw differences/intervals, evidence, sensitivity, exclusions and full provenance.
- One survivor supports a narrow one-dimensional report. No survivors supports retaining corpus description and stopping generalized ranking. Restrict claims to sources/periods actually supported.
- Only then assess deterministic structure on the same matched sermons. For semantic style, first review 12 whole sermons across ≥4 pastors, double-review ≥4, search for missed runs and evaluate current-version boundaries.
- E3 pilot targets are precision ≥.90, recall ≥.80, duration IoU ≥.70 and median absolute coverage error ≤5 percentage points, with adequate uncertainty and per-dimension support. Incremental comparison requires held-out benefit beyond Scripture, with redundancy ablations.
- Keep embeddings, PCA/clustering, semantic duration ranking and fit/quality scoring outside this milestone.

## Execution and validation handoff

Implement Steps 1–2 as bounded correctness changes, then Step 3 as the first analytical deliverable. Step 4 depends on E1 findings; Step 5 depends on surviving measures and reviewed sampling coverage. Do not build all experiments in advance.

During development run focused unit tests and inexpensive static checks only. Existing small regression command for Steps 1–2:

```bash
.venv/bin/python -m unittest tests.test_benchmark tests.test_population_analysis -q
```

Add the focused tests specified above as their implementations land. A passing unit test establishes code behavior, not measurement validity.

E1a now starts with a single-command caption review page documented in `E1A-HANDOFF.md`. E1b/E2 are not implemented yet and depend on reviewed E1a results. Brian runs all dataset validation; the agent neither launches broad evaluation/reclassification nor monitors its progress.

The main human dependency is audio-linked review and verified series/date/source metadata. Engineering can prepare packets and enforce consistency, but cannot substitute detector output for those ground-truth decisions.

## Implementation status — September 12, 2026

- Steps 1–2: diagnostic interpretation corrections, actual sermon distributions for the leading candidates, unsupported recurrence/richness bootstrap suppression, diagnostic feature exclusions, exact-current checks, explicit historical reference scope, common masks, constant-coordinate abstention, explicit ties and a fixed default core scope are implemented. Schema/analyzer versions separate new behavior from historical snapshots.
- Historical snapshots/reports remain inspectable. New comparisons require the new snapshot schema; `--historical-references` pins a specified snapshot of that schema while requiring a current candidate. It does not replay an old comparison algorithm.
- Calibration membership and candidate overlap are disclosed; independently designed calibration, construct-family redesign and validation-based eligibility gates remain E2 work. No feature has been certified.
- Step 3a infrastructure is implemented; actual audio review and E1a dataset execution are pending Brian. Step 3b and later conditional experiments are pending those findings. Production transcript normalization is unchanged.

## Handoff correction — September 13, 2026

The prior handoff assigned Brian experimental-design and annotation work. It is superseded by a prepared short-excerpt review with one command and thumbs-up/down or minor edits. This narrows the first evidence claim honestly; it does not silently lower the requirements for the later whole-sermon or E1b experiments. Codex owns selection, defaults, data preparation, interpretation and the next proposal.
