# Can these measurements support pastor-level comparison?

**Decision: defer comparison-ready pastor profiles; pursue a falsifiable test of Scripture measurement invariance and cross-series repeatability.** Preserve evidence-linked description of the collected sermons. Revise the comparison method before interpreting its rankings. Do not expand the feature set until the strongest existing signals survive transcript and sampling perturbations.

The system has a useful reproducibility foundation, but its present evidence does **not** establish persistent pastor characteristics. Its strongest candidates are detected-reference density and detected Bible-text span fraction. Even these combine pastor, source, selection, and detector behavior. The next milestone should certify a small set of reliable dimensions—or conclude that the useful product is sermon-corpus description rather than pastor similarity.

## Evidence and scope

Reviewed commit: `d627696cedfc76478617f376d8b9166156926d6e`. Database inspected read-only: `/Users/briancummings/Documents/PastorSearchData/app.db`. This review did not run corpus analysis, backfill, classification, model inference, or population resampling. It copied existing reports and saved measurement rows, summarized two already-persisted sermon measures, inspected one transcript, and ran small synthetic checks plus 19 focused unit tests, all passing.

The authoritative quantitative source is [population snapshot 2](/Users/briancummings/code/pastor-transcript-extractor/docs/analytical-review/population-snapshot-2.json), created September 7, 2026, using `scripture-population-diagnostics@2` and `profile-scripture-usage@4`, fingerprint `c81bfbee61ad029487804737339ad52edb1065693ba94608bc2b98faf7838e07`. Snapshot 1 has the same population; it is not independent replication. [Saved inputs](/Users/briancummings/code/pastor-transcript-extractor/docs/analytical-review/persisted-inputs.json), [derived summaries](/Users/briancummings/code/pastor-transcript-extractor/docs/analytical-review/summary.json), and [synthetic counterexamples](/Users/briancummings/code/pastor-transcript-extractor/docs/analytical-review/counterexamples.json) accompany this review. The summaries include input-file hashes. Snapshot membership is historical; current identity assignments and source contents have not been revalidated across the corpus.

| Available evidence | What it permits / blocks |
|---|---|
| 47 profiles, 293 distinct sermon runs and videos; 19 active, 28 provisional profiles | Exploratory distributions of these assigned profiles; not a reviewed comparison population or verified identities for all inputs. |
| 14 profiles have 3 sermons; 8 have 4; 25 have ≥5, 12 have ≥8, 9 have ≥10; maximum 17 | Unequal depth, with nearly half below the current core threshold. No demonstrated adequate-depth rule. |
| 0 dated sermons in snapshot; 2 multi-source profiles | No temporal estimate. Source checks apply to two selected profiles and cannot isolate source effects. |
| All 293 source-kind values are `extraction_proposed_json` | This is an artifact role, not evidence of one uniform ASR/caption method. |
| Profile reconstruction parity maximum absolute delta = 0 | Saved aggregation and reconstruction agree. Shared detector errors remain fully possible. |
| No reference panels, membership events, panel snapshots, or benchmark comparison runs in inspected database | No empirical nearest-reference ranking, margin, or panel-sensitivity result exists here. |
| 13 `sermon-structure@2` runs and one `profile-sermon-structure@2` aggregate, profile 59/run 56 | Within-profile structure variation only; no between-profile structure effect or incremental information estimate. No structure population snapshot. |
| 11 semantic sermon runs at version 2, one at version 1, none at current version 3 | Historical support detection; no current run-boundary coverage validation demonstrated. |

Code anchors: [Scripture aggregation](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/profile_analysis.py), [population diagnostics](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/population_analysis.py), [comparison roles](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/comparison_features.py), [benchmark calculation](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/benchmark.py), [structure](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/structure_analysis.py), [structure population calculation](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/structure_population_analysis.py), [semantic extraction](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/style_analysis.py), [semantic aggregation](/Users/briancummings/code/pastor-transcript-extractor/src/pastor_transcript_extractor/style_profile_analysis.py). Source links point to the reviewed working-tree files; the commit and saved artifacts above pin the review context.

## 1. Current capability boundary

**Description:** defensible statements concern the supplied sample and literal detector outputs: “these analyzed transcripts contain X detected references per 1,000 transcript words,” with sermon IDs, counts, denominators, and excerpts. Repeated chapters and book shares describe this collection. Human-reviewed evidence can support “this sermon contains this observable behavior.” Persistent pastor wording requires additional evidence across independently sampled series and time periods.

**Comparison:** numerical differences between these saved samples are reproducible and inspectable. They may be shown as experimental sample differences, with magnitude and variation. They cannot yet be promoted to reliable pastor similarity, a calibrated nearest reference, or a population percentile. No feature is presently certified comparison-ready merely because the role registry calls it core.

**Fit:** absent. Fit requires an explicit church preference rubric, reasons and tradeoffs for each dimension, applicable reviewed evidence, and a separate validation process. Similarity is not a fit rubric.

Categorically refuse inference of identity, theology, orthodoxy, politics, Christian nationalism, competence, character, spiritual maturity, sermon quality, or church fit from these distances. Refuse “no Scripture engagement” from no alignment; “not doctrinal” from no accepted semantic evidence; “stable pastor trait” from a short single-series corpus; “close match” solely from rank one; “speaking rate” from transcript tokens/minute; and “confidence” from a first-versus-second distance margin. Do not extrapolate to pastors, languages, sources, periods, or denominations outside the reviewed sample.

## 2. Feature decisions

The following tables jointly supply the feature decision record. Numerical evidence, within-sample sensitivity, zero rates, corpus-size associations, and uncertainty for every saved Scripture feature appear in the quantitative appendix. “S” means those saved Scripture statistics; “T” means the one-profile structure table. Neither is a causal pastor effect. Corpus-depth requirements below are **validation requirements**, not estimated sufficient sample sizes. The implementation currently uses 5 sermons for core/composition and 8 for depth-sensitive features, plus ≥10,000 words and ≥80% analysis coverage. These are exploratory policies, not validated guarantees.

Common limits for every row: convenience selection; unresolved identity error; no dates/series labels; almost complete pastor-source aliasing; no independent repeat measurement. All proposed comparative uses require E1/E2 below. Any unestimated stability, effect size, or error interval remains unknown, not zero.

| Feature / family | Literal measurement → intended construct | Evidence, confounders, depth requirement | Permissible / prohibited interpretation | Decision |
|---|---|---|---|---|
| `references_per_1000_words` | 1,000 × total accepted explicit/contextual mentions / pooled transcript words → reference frequency | S; actual sermon variation below. Caption repetitions, citation conventions, sermon length and selection. Test equal-sermon and pooled-word estimands across ≥3 series; positive precision gate required at selected depth. | Detected citation density in sample / biblical fidelity or textual depth | **validate** |
| `scripture_text_engagement_fraction` | Sum of accepted aligned transcript-span words / total transcript words → textual engagement | S; actual sermon variation below. Single bundled WEB translation, thresholds, paraphrase, repeated captions; alignment is selected text overlap. Require paired reviewed transcript/translation audit before a depth rule. | Detected Bible-text span fraction / fraction devoted to exegesis or all Scripture engagement | **revise**: rename literal output; validate revised feature |
| `multi_verse_reference_ratio` | Mentions with a parsed verse range having end > start / all mentions → extended passage use | S; 29.8% profile zeros; verbal formatting and parser matter. Need reviewed range and non-range examples, sufficient reference events and series diversity, not only 5 sermons. | Explicitly detected range-citation frequency / actual passage-reading duration or expositional depth | **validate** |
| `cross_sermon_anchor_coverage` | Maximum fraction of sermons citing any one chapter seen in ≥2 sermons → recurring anchor | S; 36.2% zeros; maximum selection, series schedule, discrete 1/n increments; duplicate-sensitive bootstrap. Require distinct-original-sermon recurrence across ≥3 series, fixed depth. | Recurrent chapter in collection / persistent textual focus | **revise** |
| `chapter_breadth_per_10_references` | 10 × distinct pooled chapters / pooled mentions → breadth | S; denominator grows after chapter discovery slows. Series, depth and transcript replication. Compare at fixed reference exposure and independently sampled sermons; 8-sermon gate insufficient. | Observed breadth at stated exposure / whole-Bible breadth or knowledge | **revise**: exposure-standardized discovery/rarefaction |
| `effective_book_count` | Reciprocal of pooled book-share HHI → effective diversity | S; depth r=.409; exactly redundant with HHI despite imperfect Pearson correlation. Balance series and citation exposure. | Diversity of detected book mentions / intellectual or theological breadth | **validate**; retain only one of reciprocal pair in distance |
| `aligned_passage_concentration_hhi` | Squared shares of alignment counts by chapter → concentration of text matches | S; LOO .681 IQR, interval width 2.932 IQR, depth r=−.495, source deletion 4.852 IQR across only 2 profiles. Sparse alignment events and translation. Need enough reviewed alignments across series; 8 sermons not enough evidence. | Concentration of detected matches / preaching focus | **revise**; likely exclude from early comparison |
| `sustained_chapter_reference_ratio` | Mentions belonging to chapters cited ≥2 times within the same sermon / all mentions → sustained chapter use | S; median .910, near ceiling. Repeated caption fragments can turn one citation into “sustained.” Require reviewed distinct citation episodes. | Repeated detected references / sustained exposition or time spent on text | **revise** |
| `mean_pairwise_book_distribution_cosine` | Average cosine of pairs of reference-bearing sermon book-count vectors → recurring book distribution | S; zero-reference sermons excluded; pair dependencies; bootstrap compares duplicate copies as if independent sermons. Require distinct-origin pair estimator and cross-series held-out sets. | Similarity of observed book distributions / general preaching consistency | **revise** |
| `reference_density_consistency` | 1/(1+population-SD/mean) of sermon citation densities → consistency | S; LOO .508 IQR; unstable low means, depth, source and mixture effects. Two sermons suffice to compute, not to establish repeatability. | This sample's density dispersion / consistency of pastor or quality | **revise**: show dispersion directly; test at fixed depth |
| `anchored_text_alignment_fraction` | Accepted alignments near detected reference anchors / all accepted alignments → citation-linked matching | S; coupled to reference and alignment detectors, translation and thresholds. More sermons do not identify detector bias. | Detector-route mixture / expository method | **diagnostic-only** |
| `mean_scripture_text_alignment_score` | Mean score among accepted Bible-text matches → match strength | S; selection by acceptance threshold, lexical/translation agreement. No depth makes this a pastor trait. | Accepted-match diagnostics / Scripture accuracy or theological faithfulness | **diagnostic-only** |
| Ten canonical shares and `old_testament_share` | Mention proportions by division/testament → distribution of cited material | S by component; compositional, zero-inflated, series-dependent. Need reviewed event counts across series and exposure. | Distribution of detected references / doctrinal emphasis or neglect | **diagnostic-only** for comparison; retain sample descriptions |
| Ten `canonical_division_clr_*` coordinates | log(count+.5) minus mean log(count+.5) → compositional contrast | Implemented but not resampled in saved population reports, which test raw shares. Zero smoothing depends on total exposure; ten coordinates have rank nine. Require E2 on the actual transformed family and pseudocount sensitivity. | Relative citation composition / ten independent pastor traits | **validate** |
| `book_breadth_per_10_references` | 10 × distinct books / mentions | S; depth r=−.416; correlation .834 with chapter breadth. Saturating numerator. | Exposure diagnostic / pastor breadth | **diagnostic-only** |
| `book_concentration_hhi` | Sum of squared book-mention shares | S; reciprocal of effective book count. | Explain concentration/diversity / additional independent signal | **diagnostic-only** in comparison; retain descriptive value |
| `zero_detected_reference_sermon_fraction`, `sermons_with_text_alignment_fraction` | Fractions with zero references / ≥1 accepted alignment | S; respectively 89.4% zeros and median 1; detector and selection effects dominate. | Coverage/detector warnings / absence or ubiquity of Scripture engagement | **diagnostic-only** |
| Coverage, attached/analyzed/missing sermons, words, durations, explicit/contextual/anchored/independent totals and confidence/method counts | Exposure and pipeline outputs | Persisted counts and evidence; size and pipeline policies dominate; one input suffices for QC. “High” confidence is a detector label, not a calibrated probability. | Corpus audit / similarity dimension | **diagnostic-only** |
| Top books, repeated chapters, testament percentages, quarter placement | Ranked counts, chapter recurrence, segment-start quarter bins | Exact evidence/run references support sample description; coarse timing, segment repetition, uncertain extraction windows; one sermon or ≥2 for recurrence. | Evidence-linked description of this collection / stable preference, attention time, or sermon arc | **retain** for description only |

Each structure row below has only T evidence: 12–13 sermons from one profile. Between-pastor effect sizes, reliability across series, and incremental value are all **not identifiable**. A ≥3-series/multiple-profile design and E1 transcript checks are required for every comparative candidate, regardless of the number of sermons currently stored.

| Structure feature | Literal measure → candidate construct | Likely confounders / permissible and prohibited interpretation | Decision |
|---|---|---|---|
| Tokens/minute | Latin/apostrophe token count / selected sermon minutes → transcript density | Captions and window boundaries; permit transcript density, prohibit speaking speed | **diagnostic-only** |
| MATTR-100 | Mean unique-token fraction in rolling 100-token windows → lexical diversity | Overlap, spelling, translation, vocabulary and topic; permit literal diversity, prohibit intelligence/eloquence | **validate** |
| First-person singular rate | I/me/my/mine/myself per 1,000 tokens → self-reference | Quotations and stories; permit token frequency, prohibit narcissism/authenticity | **validate** |
| First-person plural rate | We/us/our/ours/ourselves per 1,000 tokens → collective address | Quotation, Bible text, topic and audience; permit frequency, prohibit warmth/inclusiveness | **validate** |
| Second-person rate | You/your/yours/yourself/yourselves per 1,000 tokens → direct address | Quotation/application/topic; permit frequency, prohibit pastoral care | **validate** |
| Question-mark segment rate | Segments containing '?' / words ×1,000 → punctuation frequency | ASR punctuation and segmentation; permit QC, prohibit rhetorical questioning skill | **diagnostic-only** |
| Adjacent-eighth cosine mean | Mean content-token cosine across seven adjacent token-bin pairs → lexical continuity | Topic, length, stopwords and repetitions; permit lexical recurrence, prohibit coherent argument | **validate** |
| Adjacent-eighth cosine minimum | Minimum of those seven cosines → largest lexical discontinuity | Extreme statistic, segmentation and vocabulary; permit localized lexical change, prohibit sermon transition quality | **validate** |
| Opening/closing cosine | First/final token-eighth cosine → lexical return | Prayers, boilerplate, extraction endpoints; permit word-distribution recurrence, prohibit narrative closure | **validate** |
| Dominant-anchor share | Largest chapter count / chapter-specific references → citation concentration | Derived Scripture evidence; caption duplication and denominator differ from profile sustained ratio; permit concentration, prohibit exposition | **validate**; incremental information likely limited |
| Dominant-anchor span | First-to-last segment-ordinal difference / (sermon segment count−1) → extent of anchor recurrence | Segment count is not elapsed time; uneven caption segmentation and repeated references; permit ordinal span only | **revise** to reviewed temporal/citation-episode interpretation |
| Dominant-anchor returns | Runs returning to dominant chapter after another chapter / chapter references → reference navigation | Sparse event sequence, ties, captions and detector misses; permit detected returns, prohibit rhetorical architecture | **validate**, low priority |

Semantic dimensions are independent multilabel detections, not parts summing to 100%. Each has version-specific lexical acceptance gates in addition to model proposals. Literal occurrence therefore means **accepted model-plus-rule evidence**, not all occurrences of the semantic mode.

| Semantic dimension / output family | Evidence and construct limitation | Depth, permissible/prohibited interpretation | Decision |
|---|---|---|---|
| Exegetical exposition | Historical fixture 2 TP/0 FP/0 FN; gate favors explicit text-language cues; Scripture corroboration partly reuses Scripture evidence | Review full sermons across pastors before estimating prevalence. Positive reviewed excerpt can demonstrate explanation; cannot quantify exegesis from citation or unreviewed support duration. | **validate** support detection; comparison deferred |
| Narrative illustration | Historical fixture 2/0/0; event/action conventions and personal-story topics affect gates | Positive reviewed narrative evidence is usable; no inference about personality or overall narrative style. Need hard negatives and fully labeled misses. | **validate** support detection; comparison deferred |
| Doctrinal argument | Historical fixture 4/0/0; accepted reasoning language is not doctrine content or correctness | Reviewed reasoning excerpt only; prohibit doctrine classification, orthodoxy and sophistication. | **validate** support detection; comparison deferred |
| Practical application | Historical fixture 3/0/0; earlier baseline missed clear application; action-language gate may select phrasing | Reviewed specific-response excerpt only; prohibit effectiveness or pastoral care. | **validate** support detection; comparison deferred |
| Support counts, per-sermon/per-word rates, presence fractions, support duration, support-coverage consistency | Block opportunities, acceptance gates and excerpts determine counts and spans; total duration denominator can include incompletely analyzed material | No comparison-depth threshold established. Evidence navigation/QC only; support snippets are not total mode duration. | **diagnostic-only** for now |
| Candidate run counts, coverage, duration, presence, consistency | Current @3 extends support to model-proposed mode boundaries; saved profiles label boundaries `unreviewed` | Need full-sermon boundary review before duration prevalence. Overlap allowed; forbid interpreting four coverages as a partition. | **validate** through additional fixtures; remain evidence-only |
| Semantic analyzed coverage, rejected proposals, model provenance, Scripture corroboration | Pipeline coverage and dependent corroboration | QC, never pastor similarity | **diagnostic-only** |
| Generic “overall preaching style,” quality, theology or fit score derived from these vectors | No defensible operational link or reviewed criterion | No amount of the current measurements establishes these constructs | **abandon** these interpretations |

## 3. Empirical ceilings and falsification findings

**The strongest numerical signals are still weakly bounded.** Reference density across profiles has median 2.168 and IQR 1.535–3.028 per 1,000 words; its median conditional bootstrap interval is 1.006 population IQR wide. Text-span fraction has median 1.495%, IQR 1.087–2.372%; its median interval width is 1.072 IQR. These widths are on the same scale as interquartile profile differences. They are not evidence that typical profile pairs can be distinguished reliably. Extreme pairs might be separable, but that requires pair-specific intervals and artifact review.

The saved sermon rows allow a more relevant variation check, computed without re-running analysis:

| Quantity | Reference density /1,000 words | Detected text-span fraction |
|---|---:|---:|
| Sermon median [Q1,Q3], n=293 | 2.077 [1.207,3.201] | .01452 [.00770,.02668] |
| Sermon range | 0–14.817 | 0–.16551 |
| Median within-profile sermon SD [Q1,Q3], 47 profiles | .983 [.840,1.616] | .01219 [.00767,.01758] |
| SD across equal-sermon profile means | 1.354 | .01267 |
| Unadjusted one-way residual variance | 2.4908 | .00032910 |
| Unadjusted profile-intercept variance, method of moments | 2.2561 | .00013577 |
| Unadjusted ICC | .475 | .292 |

The method uses MS-between/MS-within and the standard unequal-group effective n, explicitly implemented in `summarize.py`. These are **descriptive unadjusted estimates**, not isolated pastor variance. No uncertainty interval for these ICCs was estimated; existing bootstrap intervals concern profile aggregates, not the ICC. Sources and sermon selection can produce the entire apparent profile component. Residuals combine sermon variation and measurement error. Profile means here weight sermons equally; the production ratios weight by words, so their SDs differ. Do not mix these estimands.

Under the deliberately optimistic independent-sermon random-intercept model, mean reliability would be nρ/[1+(n−1)ρ]: at n=5/8/10, about .819/.879/.901 for density and .673/.767/.805 for text-span fraction. These are algebraic illustrations, **not adequate-depth recommendations**. Series correlation, stable source bias and uncertain ICCs invalidate treating them as achieved reliability. A biased detector can become very reproducible as n grows.

**The current Scripture variance ratio overstates the relevant separation.** `_profile_stability` computes variance of n almost-identical leave-one-out aggregates. For an ordinary mean, Var(leave-one-out means)=Var(sermons)/(n−1)² using population-variance conventions. Thus at 5 sermons it is 16 times smaller, at 10 it is 81 times smaller. The synthetic check verifies 16. The report labels this an LOO estimate, but dividing between-profile variance by it does not estimate ICC, pastor/sermon variance ratio, or generalizability. For nonlinear pooled ratios, there is no universal correction factor. Rename it aggregate deletion sensitivity and estimate actual sermon variation separately.

**Depth evidence is confounded.** `stability_by_minimum_sermons` changes the eligible cohort, retaining each profile's full sample. It does not compare n=3/5/8/10 samples from the same pastors. Its high-stability fractions .418/.490/.627/.667 cannot establish that eight sermons suffice. The role recommendation function also inherits the hand-assigned core/depth roles; these recommendations are not independent validation of those roles. A median “high” label can hide many unstable profiles.

**Transcript artifacts are observed, not hypothetical.** Saved run 145, video `CaB0_qUCwms` (“Jason Shaw \"Power\"”), has 33,630 words over 4,323.49 seconds, approximately 467 words per minute. Inspection of its current canonical input matched saved SHA-256 `becf40db7f06926abb85b86ed12ca19ccc2294a59b26f4d40b7ed60f80bda4cb`. Segments 1683–1685 repeat the same “Romans 3:24” phrase in overlapping/incremental captions around 1972.559–1979.029 seconds; the middle segment lasts .01 seconds. The saved chapter count for Romans 3 is 3. This is strong evidence that a reference count can count transcript presentation rather than distinct spoken citation episodes. It is one inspected sermon, not an estimated population error rate.

`_load_sermon_source` retains selected segment texts; `analyze_sermon` joins them for word counts, and reference detection operates per segment. The existing rolling-caption normalizer is used elsewhere, including classification prompts and exports, but is not applied to these analytical inputs. Uniform duplication might cancel in some ratios; uneven duplication, thresholded “≥2” recurrence, lexical diversity, segment timing and distinct-count ratios do not enjoy that protection. Do not apply the prompt normalizer blindly as ground truth: it can also remove legitimate repetition. Validate an evidence-preserving analytical normalization against audio/reviewed transcripts.

**Bootstrap recurrence is not recurrence across independent sermons.** With two distinct sermons citing different books/chapters, true cross-sermon coverage and pairwise cosine are both 0. A bootstrap sample containing two copies of only one sermon makes both 1 in the current aggregator. Ordinary bootstrap duplicates are appropriate for many means, but here they create fictitious distinct-sermon relationships. The resulting intervals do not validate cross-sermon constructs. Fixed-depth disjoint subsets or an estimator that preserves original-sermon identity are necessary. Pooled richness estimates also need explicit exposure/bias treatment rather than naive bootstrap confidence language.

**Detector ceilings:** WEB lexical matching excludes many short, paraphrased, translated or unrecognized quotations by design. Accepted-score averages measure successful detector matches. Saturated sustained-reference ratio (median .910), aligned-sermon presence (median 1), and sparse multi-verse/anchor measures limit useful discrimination. Minor-prophets share has 53.2% zeros and median LOO/interval width zero: this is lack of observed events, not proof of stable avoidance. The breadth/HHI families cannot escape series and exposure dependence merely through normalization.

**Variance components that cannot be identified:**

| Component | Why blocked | Smallest additional evidence |
|---|---|---|
| Pastor separate from source/church | 45/47 profiles single-source; two cross-source observations do not balance source, venue, time and topic | Several pastors crossed with recording/transcript methods, preferably paired versions of the same sermon; shared source environments when feasible |
| Series/topic | No reviewed series/topic strata in frozen report; book composition is itself an outcome and cannot be the sole adjustment | Series ID plus manually reviewed topic/passage strata for the small E2 pilot |
| Time/change | Zero dates in snapshot; publication date may not equal preaching date | Verified sermon dates and ≥2 periods within each pastor, crossing series where feasible |
| Sermon vs measurement error | One derived measurement per sermon; deterministic rerun adds no replicate | Same sermon under reviewed/manual vs original transcript, and independent label review; model repeats for semantic error |
| Selection vs pastor | Convenience corpus and active/provisional identity states | Prespecified sampling frame with eligible/excluded sermon list and reviewed identity for included material |
| Structure/style incremental effect | Only one structure profile; no current semantic @3 corpus | Same reviewed sermons/pastors in both baseline and added-feature arms, held-out series |

No numerical hard ceiling for general pastor comparison can yet be estimated. The negative evidence establishes serious practical ceilings for current **implementations and interpretations**; it does not prove pastors have no persistent observable characteristics.

Upstream localization also matters. The checked-in [localization baseline](/Users/briancummings/code/pastor-transcript-extractor/evaluation/baselines/sermon-localization-v1.json) pins a different July commit and 42 fixtures: mean sermon recall .9923, worst recall .9012, mean contamination .1022. These are historical fixture results, not an error estimate for the September measurement population. They show why high recall alone cannot guarantee uncontaminated sermon measurements. E1 should review selected sermon boundaries and speaker attribution along with transcript representation. The Scripture-reference fixture has 25 cases including 10 negatives; the alignment fixture has 12 including 5 negatives, both labeled code-assisted reviews. They provide bounded regression evidence, not sampled-corpus detector precision/recall or inter-reviewer reliability.

## 4. Comparison-method decision: revise, and defer public ranking

Retain immutable snapshots, named membership review with rationale, fingerprints, exclusion lists, source-scale differences, and explicit interpretation limits. These are valuable analytical controls. The present distance is reproducible arithmetic, not a validated similarity measure.

| Method concern | Current implementation and required decision |
|---|---|
| Transformations | Most rates, bounded fractions and count-derived metrics remain raw. Prespecify literal-scale reporting; test log/log1p for positive skew and event-count models for bounded/sparse proportions. Do not select transforms for attractive separation. |
| Robust normalization | Frozen panel MAD×1.4826 is a reasonable exploratory default; range fallback makes zero-MAD sparse dimensions depend on extremes. Require minimum support and a fixed reviewed calibration population; report fallback/sensitivity. Scaling mixed-unit SDs relative to the median SD in population diagnostics is not a meaningful importance measure. |
| Constant dimensions | No positive scale means silently skipped. Synthetic test gives distance 0 despite candidate=100/reference=0 on a constant-panel feature. Require explicit out-of-panel difference/abstention; absence of panel variance cannot imply closeness. |
| Compositions | CLR with .5 counts is better than ten raw independent proportions. However, total count controls shrinkage; resampling raw shares did not validate CLR. Coordinatewise MAD scaling and capping are a chosen weighted log-ratio geometry, not ordinary Aitchison distance. Test an explicit family distance and smoothing at matched exposure. |
| Family weights | Equal RMS across `core`, `canonical_composition`, and `depth_sensitive`; these last two depth labels are not coherent constructs. At core level each of four scalar features has 1/8 squared-distance weight; each of ten CLR coordinates 1/20. At full level these change to 1/12 and 1/30, and each depth feature gets 1/24, before missingness. Choose construct-based families, remove detector diagnostics, freeze weights, test plausible alternatives. |
| Correlation | Within-family RMS does not remove correlated information. HHI/effective count are exact reciprocal redundancy despite Pearson −.790. Correlation threshold .90 misses it. Audit deterministic dependencies and cross-family effects; do not fit unstable high-dimensional covariance with 12 deeper profiles. |
| Missingness | Missing optional coordinates are skipped per pair; empty families are skipped and weights redistributed. Different references can be ranked in different geometries. Use a common supported mask per comparison or abstain; disclose every omitted dimension and effective weight. Never impute a missed detector result as pastor absence. |
| Ranking and absolute closeness | Cap at 5 scale units compresses extreme differences; ties are broken by profile ID. No calibrated absolute-close gate. A nearest reference may be far; report raw differences and a set of indistinguishable references instead of mandatory winner. |
| Top-two margin | Absolute and relative margins are computed and correctly called descriptive, but have no sampling distribution or gate. Require resampled margin uncertainty and a practically meaningful gap. |
| Panel composition | Reviewed membership is implemented, but no population representativeness follows from manual inclusion. Candidate self-match excluded from rankings, yet candidate may remain in frozen normalization statistics. Full-depth reference filtering also leaves core scales based on a broader cohort. Declare calibration population separately and test deletions/additions and recomputed scales. |
| Depth discontinuity | At 8 candidate sermons the system switches to full features and excludes shallower references. A seventh-to-eighth sermon can change features, weights and panel simultaneously. Freeze comparison scope for sensitivity tests; compare common core separately. |
| Freshness | Benchmark uses `get_compatible_speaker_profile_analysis_run`, which selects latest matching key/version, not exact-current membership/source fingerprint. Style aggregate similarly selects latest matching analyzer version, although it rejects mixed model/prompt configurations. Exact-current checks or explicitly pinned historical scope are necessary to avoid reproducible stale claims. |
| Abstention | Current eligibility gates cover words, sermon count, analysis coverage, schema, and available references. Missing: reviewed identity, series/time coverage, calibrated effect precision, adequate event counts, fixed feature support, out-of-panel status and unstable rankings. Add these only as tied to the validation findings. |

Nearest-reference stability is **unknown**, because no persisted comparisons exist. The population LOO statistics concern individual raw features, not transformed vectors or rankings. Even stable coordinates can swap near-tied references. Conversely, an unstable coordinate may not change the nearest reference if all alternatives are far. Neither conclusion can be inferred without E2.

## 5. Smallest decisive experiments, ranked by decision value

All numerical thresholds below are **proposed preregistered pilot gates**, not empirically justified constants. Brian and the intended report users should select practical tolerances before viewing results. Report intervals and inconclusive outcomes; do not relax gates after looking. The pilot can reject directions with small samples; it cannot certify broad deployment on its own.

**E1 — Same-sermon measurement invariance and event audit (highest value).**

- Decision: whether any present Scripture/stylometry differences survive transcript representation, and which implementations must change before comparing pastors.
- Hypothesis: for the leading two Scripture features, paired original and reviewed transcript representations differ by less than .2 of the frozen population IQR for most sermons, without a source-linked shift.
- Minimum data: 12 existing sermons from 6 reviewed pastors, two each, spanning caption formats and low/high measured values; include run 145 and a second independently chosen example. Obtain audio-linked reviewed citation episodes and text spans; use multiple Bible translations where present. Double-review four sermons; adjudicate differences. The unit is the sermon, not each correlated reference.
- Method: freeze original run IDs/hashes; produce reviewed alternative text with token/segment provenance; compare original/reviewed density, text-span fraction and sustained-reference ratio. Inspect a limited set of lexical features on the same pairs. Compare signed and absolute paired shifts; evaluate event precision/recall and duration/word-span error. Do not merely run the same deterministic detector twice.
- Effect/reliability: median and 90th-percentile absolute paired shift in literal units and frozen IQR units, paired bias, proportion of distinct citation episodes recovered, overlap-span precision/recall; cluster uncertainty by sermon/pastor. Four double-reviews expose label ambiguity but do not precisely estimate it.
- Pass/fail: pilot pass if median absolute shift ≤.10 IQR and 90th percentile ≤.25 IQR for a candidate, with no reviewed subgroup bias >.20 IQR; target episode precision ≥.95 and recall ≥.85 with sufficiently narrow uncertainty for the intended claim. If intervals cannot establish the error bound, call it inconclusive. A small high apparent precision sample alone is not certification.
- Confounders: reviewer normalization can erase real repetition; transcript translation and sermon-window changes must be separated; source pairing does not remove all venue effects.
- Positive: take surviving literal measures to E2. Negative: revise analytical normalization/episode counting and engagement label, revalidate only affected measures. Inconclusive: add the few transcript/source strata responsible for uncertainty, not a broad backfill. Stop pursuing alignment score or anchor-route proportion as pastor traits regardless of this result.

**E2 — Cross-series repeatability and fixed-panel perturbation (decides the product direction).**

- Decision: whether a persistent, useful profile exists at feasible depth; whether a reference comparison can be issued reliably.
- Hypothesis: independent, series-separated samples from the same pastor are closer than practically different pastors, and meaningful pairwise differences survive source/series and panel perturbation.
- Minimum data: first audit the 9 existing profiles with ≥10 sermons for verified identity and usable sampling coverage. Target 8 pastors ×12 sermons, four sermons from each of ≥3 series across ≥2 dated periods. This is a staged pilot minimum, not a power calculation or representative panel. If existing material lacks this coverage, annotate/collect only the missing strata. Require cross-method pairs from E1; general source independence remains restricted without a more crossed design.
- Method: within the same eligible pastors, compare matched depths and disjoint subsets; hold out series and periods, not just random sermons. Estimate one-way/multilevel variance only where design rank supports it; nested series within pastor must not masquerade as crossed topic control. For aggregate richness/recurrence use original-sermon-aware estimators and fixed exposure. Freeze a reviewed pilot panel and actual transformed feature schema. Perturb candidate and reference sermon samples independently. Perform leave-one-sermon/series/source deletion; delete panel members other than the winner to test scale effects, remove the winner to characterize alternatives, and add reviewed plausible anchors. Test both fixed and refitted calibration scales. Keep feature masks fixed.
- Effect/reliability: within/between disjoint-sample distance distributions; same-pastor-vs-different-pastor concordance/AUC (not identity recognition); generalizability at n; raw and standardized pair differences with cluster intervals; top-reference inclusion probability, top-k overlap, rank correlation and top-two margin intervals; out-of-panel rate and abstention frequency. Partition uncertainty by pastor/series; never treat all pairwise distances as independent.
- Pass/fail: proposed dimension gate: reliability at the chosen depth ≥.80 with lower interval bound ≥.70; a reportable pair difference must exceed a preregistered meaningful threshold (provisionally .5 between-profile SD) and its interval must exclude the ±.2-SD negligible zone. Proposed family gate: same-pastor concordance ≥.80 with lower bound >.65. A named nearest reference requires ≥.80 selection under sermon/series resampling, retention under ≥.80 prespecified nonwinner-panel perturbations, and top-two margin interval above a preregistered nontrivial gap; otherwise report an uncertainty set or abstain. A removed winner cannot be expected to remain nearest. A close label additionally needs calibrated absolute distance. Eight pastors may leave these intervals inconclusive; expand only if a promising effect warrants it.
- Confounders: topic/source aliasing, unequal lengths and event exposure, identity errors, panel membership selection and same-sermon overlap. Same-source repeatability alone passes only a restricted within-source claim.
- Positive: build the evidence-linked comparison report for the surviving dimensions and tested domain/depth. Negative: preserve corpus descriptions; stop overall distance/ranking if no family survives. A single survivor warrants a one-dimensional difference report, not a comprehensive style profile. Inconclusive: target additional series or methods, not more sermons from the same series.

**E3 — Conditional incremental information from structure/style (only after E1/E2).**

- Decision: whether either family deserves further investment beyond Scripture.
- Hypothesis: adding a validated feature family improves out-of-series reproducibility or discrimination beyond the frozen Scripture baseline, without reducing calibration or raising source sensitivity.
- Minimum data: E2's matched sermons for all feature arms. Start with deterministic structure on those inputs. For semantic extraction, first fully annotate 12 whole sermons across ≥4 pastors with overlapping mode runs and explicit missed-run search; double-review ≥4. Cover each dimension sufficiently; absence of enough positive runs blocks that dimension. Freeze model digest, prompts, gates and blocks.
- Method: first evaluate semantic support and run boundaries. Then compare Scripture-only, structure-only, semantic-only and combined models on held-out pastors/series as appropriate, with nested feature selection. Test residual association and out-of-sample benefit, not only low correlation. Scripture-anchor structure features and corroborated exegesis get explicit redundancy ablations.
- Measures/gates: semantic pilot target run precision ≥.90, recall ≥.80, duration IoU ≥.70, median absolute coverage error ≤5 percentage points, plus subgroup/cluster uncertainty; inadequate intervals mean inconclusive. For added families, provisional ≥.05 held-out concordance improvement with interval excluding zero and no loss of E2 reliability; alternatively a prespecified practically useful new descriptive dimension meeting E2's own gate. No improvement after controlling Scripture/topic/source is a negative result.
- Confounders: feature-selection leakage, model-specific language cues, Scripture-dependent corroboration, correlated window observations, selective full-sermon annotation, and transcript errors.
- Positive: add only validated independent dimensions. Negative: keep structure descriptive; abandon semantic duration ranking if boundaries remain unreliable and keep reviewed excerpts. Inconclusive: improve the deficient label stratum or defer; do not launch general embeddings, PCA, clustering or model-scale expansion.

## 6. Semantic-style and structure roadmap decision

**Structure: remain descriptive and evidence-only while E1/E2 run; defer comparison expansion.** Current mean tokens/minute 340.9 and MATTR .337 in the single profile are consistent with substantial transcript representation effects, but only the inspected Scripture sermon proves duplication directly. The anchor-span median .0198 versus mean .138, and return-rate median 0 versus mean .0109, warn against mean-only profiles. Validate lexical diversity/pronoun/continuity measures on matched data before ranking. Redesign ordinal anchor span. Keep token density and punctuation diagnostic-only. Independent pastor information has not been demonstrated.

**Semantic style: additional fixture validation, evidence-only, comparison deferred.** The favorable historical `gemma3-4b-v3-baseline.json` actually says analyzer version **2**, prompt `sermon-style-evidence-v3`, acceptance gates v1, and 11 TP/0 FP/0 FN across 12 cases including 5 negatives. Current code is analyzer **3**, prompt `sermon-style-runs-v1`, gates v2, 512-token budget and 75-second/3,600-character blocks. A filename containing v3 is not validation of the current analyzer. The older v2 baseline has 9 TP/0 FP/1 FN on a different fixture version, so this is not a clean paired model improvement estimate.

Even treating the 11 successes as independent Bernoulli observations, an illustrative Wilson 95% lower bound is only about .741; for 2/2 it is .342, and for 5/5 negatives .566. Curated dependent examples are less informative for corpus generalization than those illustrations assume. Neither baseline validates full-mode duration boundaries, missed runs in whole sermons, or pastor stability. The implementation has a useful full-sermon review/evaluation workflow; use it before any duration comparison. Independent information beyond Scripture remains unmeasured, not established by adding four semantic labels.

## 7. Comparison-report specification

The report should lead with its scope: “Comparison of the reviewed sermon samples collected for A and B,” or, only after validation, a specifically bounded pastor-level statement. Show a small set of independently supported dimensions, never a single quality/fit score.

1. **Coverage card:** reviewed identity status; included/eligible/excluded sermons; distinct series; verified date range; sources and transcript methods; words, citation/alignments counts; coverage/missingness; depth criterion and whether met. Expose the exact inclusion manifest.
2. **Dimension rows:** literal measure and units; equal-sermon or word/event-weighted estimand; profile estimate and interval; within-pastor distribution; raw pair difference; standardized magnitude; practical equivalence/difference/indeterminate status. Show enough individual sermons to expose exceptions.
3. **Evidence:** links to source sermon, timestamps, transcript excerpt and detector/review IDs; representative examples and contradictory cases, not only the largest contribution to the distance. For corpus statistics, cite all contributing run IDs and make aggregation inspectable.
4. **Similarity results:** stable commonalities and differences first. If certified, show close-reference set, actual distances, margin uncertainty and selection frequencies; distinguish “nearest among this panel” from “absolutely close.” Tied IDs must never imply meaningful ordering.
5. **Sensitivity:** range of estimates/ranks under sermon/series deletion, balanced subsets, source pairing and panel changes; fraction of prespecified perturbations retaining the conclusion; failed scenarios plainly visible.
6. **Omissions/abstentions:** list unreliable, sparse, stale, missing, unvalidated and redundant dimensions separately with reasons. Explicitly abstain when no dimension survives, identity is unreviewed, source effects cannot be bounded, sampling is insufficient, or alternatives cannot be distinguished.
7. **Interpretation boundary:** observable description, measured comparison, and preference-based fit are separate sections/data objects. Fit is omitted unless an explicit rubric is supplied and validated. Similarity says nothing about quality, identity, theology, orthodoxy or fit.
8. **Reproducibility:** analyzer/schema/model versions, original and reviewed transcript hashes, exact sermon/profile run IDs, panel snapshot/fingerprint, calibration population, feature mask/weights, sampling seed and procedure, reviewer provenance and report version.

Do not convert aggregate uncertainty into individual-sermon certainty or describe narrow detector-repeatability intervals as uncertainty about the construct itself.

## 8. Supporting engineering and operator commands

Only the following engineering serves the analytical decision:

- Freeze a small, reviewed sermon manifest with original run IDs/hashes, verified identity, series, sermon date, passage/topic, source and actual transcript method. This supplies design variables and prevents changing samples from masquerading as improved measurement.
- Add a paired analytical-text/episode representation with source token/segment provenance if E1 shows material bias. Preserve originals and human-review corrections. Reuse existing normalization only after validation; no general pipeline rewrite is warranted.
- Build a small **offline, manifest-driven** E1/E2 harness: distinct-original-sermon resampling, matched-depth curves, actual CLR/family distances, common masks, panel perturbations, raw effect/cluster uncertainty summaries. Reject rank-deficient variance models. Its output must freeze exact inputs and policy. This is the missing analytical functionality, not a recommendation for a new architecture.
- Rename LOO variance fields/interpretation, expose actual sermon variance, and stop representing minimum-depth cohort comparisons as learning curves. Necessary to avoid false reliability claims.
- Enforce exact-current inputs or explicit historical pinning in benchmark/style aggregation; disclose omitted/constant coordinates. Necessary for traceable comparisons, not optional cleanup.
- Reuse existing style review packets for independently reviewed whole-sermon modes, missed runs and boundaries. Add incremental comparison only after those pass.

The following commands are executable **now**. Run from `/Users/briancummings/code/pastor-transcript-extractor`. The first group only reproduces this review's small offline summaries/checks:

```bash
.venv/bin/python docs/analytical-review/summarize.py
.venv/bin/python docs/analytical-review/check_counterexamples.py
.venv/bin/python -m unittest tests.test_benchmark tests.test_population_analysis -q
```

Brian can export/inspect the already saved snapshot (this is not new validation):

```bash
.venv/bin/pte analysis population-show --snapshot-id 2 --json \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

After reviewing/correcting inputs, **only Brian should run** any desired dataset diagnostics. These existing commands do not implement E2's controlled series/depth/ranking experiment:

```bash
.venv/bin/pte analysis population-build --minimum-sermons 3 --bootstrap-samples 200 --json \
  --base-dir /Users/briancummings/Documents/PastorSearchData
.venv/bin/pte analysis structure-population-build --minimum-sermons 3 --json \
  --base-dir /Users/briancummings/Documents/PastorSearchData
```

Interpretation: require exact reconstruction parity, inspect per-profile uncertainty and source/depth sensitivity, and apply the LOO/bootstrap cautions above. Structure population results with one profile cannot support between-pastor conclusions even if the command succeeds. Do not run broad structure backfill merely to make this report larger.

Focused detector regression commands available for Brian after E1 implementation changes:

```bash
.venv/bin/pte analysis evaluate-scripture-detector evaluation/scripture-references/contextual-v1.json
.venv/bin/pte analysis evaluate-scripture-alignment evaluation/scripture-alignments/reviewed-v1.json
```

Interpretation: all fixture expectations should pass, but these code-assisted curated cases do not replace the paired real-sermon audit. A clean regression result cannot satisfy E1 by itself.

After E3's full-sermon review packets have been produced and reviewed, Brian can run the implemented boundary evaluator with an explicit list (replace paths with the actual completed packet paths):

```bash
.venv/bin/pte analysis evaluate-style-boundaries /absolute/path/first-reviewed-packet.json /absolute/path/second-reviewed-packet.json
```

Assess per-dimension run precision/recall and duration IoU against E3, including missed runs and reviewer disagreement. The command accepts more packet paths; the two shown illustrate invocation, not sufficient sample size. No current CLI implements E1's paired perturbation analysis or E2's cross-series/ranking uncertainty. Implement the bounded harness above before those dataset runs; inventing a runnable command for it would conceal the main missing milestone. Metadata/audio review is manual work, with no existing command that can validly substitute for it.

## 9. Single next analytical milestone

**Complete a reviewed Scripture-signal certification pilot: determine whether any literal Scripture dimension supports reproducible, practically meaningful comparison across independently sampled sermon series after transcript error is bounded.** This is a decision milestone with a valid negative outcome.

Start with E1, then E2 only for survivors. Freeze the decisions, exact inputs and practical thresholds before executing. Do not build a richer benchmark, generalized stylistic embeddings, PCA/factors, clusters, semantic duration ranking, church-fit scores, or additional reference populations yet.

Acceptance requires: (1) a reviewed manifest and explicitly limited target population; (2) paired evidence bounding transcript/detector error; (3) separation of sermon variation from LOO sensitivity and explicit non-identifiability of confounded components; (4) matched-depth, cross-series repeatability intervals for every proposed dimension; (5) practical magnitude and uncertainty gates for pair claims; (6) actual-transform and panel perturbation results with reproducible abstentions; and (7) a frozen retain/revise/stop decision and evidence-linked sample report. “No feature survives” completes the milestone if supported by the prespecified experiment; it does not justify publishing rankings.

Roadmap changes: transcript-dominated effects → repair analytical representation first; reference density survives alone → narrow citation-density report; composition fails across series → restrict it to corpus/series description; only source-specific stability survives → explicitly source-restricted product; Scripture fails but independently validated structure survives → structure-based descriptive comparison; semantic boundaries fail → stop duration modeling and keep reviewed evidence retrieval; widespread inseparability at feasible depth → abandon generalized nearest-pastor similarity.

## Quantitative appendix

The generated tables below report **sample distributions and uncertainty/sensitivity**, not population-generalizable effect estimates. No tests of statistical significance were used to declare validity. B is between-profile median [Q1,Q3]; L is median maximum leave-one-sermon-out change in population-IQR units; U is median width of the existing 200-resample conditional bootstrap interval in those units; Z is fraction of observed profile values equal to zero; r(n) is Pearson correlation with sermon count. Every saved Scripture feature has 47 observed/nonmissing profile values. Zero/reference-presence features use a fallback scale when IQR=0. U is untrustworthy as a cross-sermon recurrence interval for the duplicate-sensitive features identified above and is conditional on the collected sample for all others. Full ranges, SDs, variances, per-profile intervals and source-sensitivity outputs remain in the accompanying JSON.

| Scripture feature | B: median [Q1,Q3] | Between-profile SD | L | U | Z | r(n) |
|---|---:|---:|---:|---:|---:|---:|
| `acts_share` | 0.0173 [0.0000,0.0603] | 0.0579 | 0.191 | 0.885 | 38.3% | 0.005 |
| `aligned_passage_concentration_hhi` | 0.0977 [0.0576,0.1405] | 0.0966 | 0.681 | 2.932 | 0.0% | -0.495 |
| `anchored_text_alignment_fraction` | 0.5185 [0.3852,0.6000] | 0.1916 | 0.394 | 1.625 | 0.0% | 0.031 |
| `book_breadth_per_10_references` | 1.0791 [0.8076,1.3592] | 0.7142 | 0.516 | 1.304 | 0.0% | -0.416 |
| `book_concentration_hhi` | 0.1524 [0.1009,0.2106] | 0.1101 | 0.600 | 2.122 | 0.0% | -0.355 |
| `chapter_breadth_per_10_references` | 1.6667 [1.3790,2.0639] | 0.7991 | 0.451 | 1.632 | 0.0% | -0.278 |
| `cross_sermon_anchor_coverage` | 0.2857 [0.0000,0.4000] | 0.2384 | 0.119 | 1.111 | 36.2% | 0.140 |
| `effective_book_count` | 6.5631 [4.7486,9.9184] | 3.0338 | 0.381 | 1.082 | 0.0% | 0.409 |
| `general_epistles_share` | 0.0354 [0.0147,0.0764] | 0.0769 | 0.426 | 1.352 | 19.1% | -0.081 |
| `gospels_share` | 0.2233 [0.1423,0.3537] | 0.1616 | 0.348 | 1.598 | 4.3% | 0.004 |
| `historical_share` | 0.0171 [0.0000,0.0425] | 0.0853 | 0.339 | 1.158 | 40.4% | 0.118 |
| `major_prophets_share` | 0.0541 [0.0235,0.1358] | 0.1092 | 0.278 | 1.148 | 19.1% | -0.020 |
| `mean_pairwise_book_distribution_cosine` | 0.2130 [0.1041,0.2748] | 0.1472 | 0.375 | 3.083 | 2.1% | 0.065 |
| `mean_scripture_text_alignment_score` | 0.6541 [0.6269,0.6783] | 0.0461 | 0.471 | 1.669 | 0.0% | -0.108 |
| `minor_prophets_share` | 0.0000 [0.0000,0.0242] | 0.0491 | 0.000 | 0.000 | 53.2% | 0.064 |
| `multi_verse_reference_ratio` | 0.0177 [0.0000,0.0338] | 0.0349 | 0.211 | 1.070 | 29.8% | 0.076 |
| `old_testament_share` | 0.3636 [0.2016,0.4786] | 0.1785 | 0.346 | 1.503 | 0.0% | 0.096 |
| `pauline_epistles_share` | 0.1250 [0.0778,0.2222] | 0.1771 | 0.314 | 1.234 | 4.3% | -0.135 |
| `pentateuch_share` | 0.0943 [0.0319,0.1695] | 0.1046 | 0.449 | 1.507 | 12.8% | -0.042 |
| `reference_density_consistency` | 0.6858 [0.6084,0.7542] | 0.0976 | 0.508 | 1.794 | 0.0% | -0.269 |
| `references_per_1000_words` | 2.1685 [1.5348,3.0281] | 1.3119 | 0.249 | 1.006 | 0.0% | 0.272 |
| `revelation_share` | 0.0526 [0.0065,0.1429] | 0.1482 | 0.253 | 0.893 | 23.4% | 0.081 |
| `scripture_text_engagement_fraction` | 0.0149 [0.0109,0.0237] | 0.0106 | 0.240 | 1.072 | 0.0% | 0.125 |
| `sermons_with_text_alignment_fraction` | 1.0000 [0.9706,1.0000] | 0.1022 | 0.000 | 0.000 | 0.0% | -0.053 |
| `sustained_chapter_reference_ratio` | 0.9099 [0.8582,0.9413] | 0.1300 | 0.437 | 1.731 | 0.0% | 0.114 |
| `wisdom_poetry_share` | 0.0531 [0.0151,0.0913] | 0.0899 | 0.499 | 1.876 | 21.3% | 0.115 |
| `zero_detected_reference_sermon_fraction` | 0.0000 [0.0000,0.0000] | 0.0947 | 0.000 | 0.000 | 89.4% | -0.049 |

T: persisted structure summaries for profile 59/run 56. SD is actual within-profile population SD. No between-profile SD or effect can be estimated from one profile. No confidence intervals are stored.

| Structure feature | Observed sermons | Mean | Median | Within-profile SD |
|---|---:|---:|---:|---:|
| `adjacent_eighth_lexical_cosine_mean` | 13 | 0.3205 | 0.3449 | 0.0692 |
| `adjacent_eighth_lexical_cosine_min` | 13 | 0.1988 | 0.2097 | 0.0666 |
| `dominant_scripture_anchor_return_rate` | 12 | 0.0109 | 0.0000 | 0.0281 |
| `dominant_scripture_anchor_share` | 12 | 0.6132 | 0.4500 | 0.2952 |
| `dominant_scripture_anchor_span_fraction` | 12 | 0.1381 | 0.0198 | 0.2256 |
| `first_person_plural_per_1000_words` | 13 | 25.2662 | 23.7189 | 9.2167 |
| `first_person_singular_per_1000_words` | 13 | 15.0942 | 16.3630 | 8.7236 |
| `moving_average_type_token_ratio_100` | 13 | 0.3371 | 0.3101 | 0.0949 |
| `opening_closing_eighth_lexical_cosine` | 13 | 0.2153 | 0.1949 | 0.0988 |
| `question_mark_segments_per_1000_words` | 13 | 3.9778 | 3.9494 | 2.3262 |
| `second_person_per_1000_words` | 13 | 20.4112 | 22.8830 | 5.4031 |
| `transcript_tokens_per_minute` | 13 | 340.9230 | 363.0463 | 71.0064 |

## Decision memo

- **Trusted now:** reproducible arithmetic on pinned inputs and evidence-linked descriptions of the analyzed sample; reviewed positive excerpts within their literal scope.
- **Most likely to fail:** detector-score/route proportions, sparse or saturated features, pooled breadth and series-dependent recurrence, and semantic support/run duration interpreted as pastor style. Caption representation is an observed cross-cutting threat.
- **Highest information value:** same-sermon original-versus-reviewed transcript/event audit, followed by cross-series repeatability of only the survivors.
- **Build after a pass:** a narrow comparison report showing meaningful raw differences, sermon variation, independent evidence, sampling/panel sensitivity and explicit abstentions.
- **After a failure:** revise contaminated measurements; stop unsupported distance dimensions; keep corpus description and reviewed evidence; defer generalized nearest-pastor and church-fit products.
