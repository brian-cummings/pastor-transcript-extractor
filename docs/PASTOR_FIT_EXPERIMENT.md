# Pastor fit experiment: can cheap text fingerprints tell pastors apart and find the ones who fit a church?

**Status: specification only (2026-11-24). Nothing is built or run. Brian approves section 9 before any code.**

## 1. Why this experiment

The end goal is **helping a church find a pastor who is likely to fit its needs** (Brian,
2026-11-24). Profiles, dimensions and benchmark distances are means to that end, not the
deliverable.

The work so far (bound-claim pilot, object-position check, thought-unit sections 13 to 31)
worked at the level of individual claims and ended without a usable product. Two findings from
it shape this experiment:

- Claim-level extraction is accurate enough when it fires (records 90 to 96% correct;
  `THOUGHT_UNIT_EXPERIMENT.md` 28.18), but it is costly per sermon, and the loss is downstream,
  in aggregation and speaker attribution (31.6, 31.7).
- Nothing so far tests whether any measurement captures what is **distinctive and repeatable
  about a pastor**, which matching needs first.

Political science (Wordscores, Wordfish), economics (phrase-based partisanship) and finance
(reference-library phrase measures on earnings calls) place speakers on scales from large text
collections without per-claim extraction. Pew's *Digital Pulpit* (about 50k sermons) and
Boussalis, Coan and Holman (about 110k sermons) did this for sermons at scale. This experiment
tests whether the same kind of cheap, local, transparent fingerprint works on our corpus before
any more paid extraction is spent.

## 2. The questions, in order

1. **Distinctness (Part 1):** does a pastor's text look more like the same pastor's other
   sermons than like anyone else's, including other preachers at the same church?
2. **Identity pre-filter (Part 1b):** given one sermon, does the text fingerprint put the right
   profile in its top five, so voice comparison could run on five profiles instead of all?
3. **Church fit (Part 2):** churches with several preachers on their channel have already chosen
   them. If we describe the church from its other preachers, does the held-out preacher rank
   near the top of all pastors?
4. **Needs (Part 3, design only):** which of a church's actual needs can sermons answer, and with
   which technique? This part produces a list for approval, not a run.

Parts 1 and 2 use **no LLM, no Jev call and no voice processing**. They run locally on Brian's
machine in minutes.

## 3. Data (counted read-only from `app.db`, 2026-11-24)

- Population: the 47 profiles with a profile-analysis run (293 sermons, 37 church channels). The
  wider registry has 318 speaker profiles; the rest have no analyzed sermons and are not used.
- Each `sources` row is a different church's channel. Eight channels carry two or three analyzed
  preachers; profile 119 appears on two channels.
- No analyzed video has a publication date, so halves cannot be split by time (limit, section 8).
- Text: the existing sermon window of each extraction, loaded the way sermon analysis loads it
  (`sermon_analysis._load_sermon_source`), with the existing caption-repeat removal. Who is
  speaking inside the window is **not** re-checked (no voice scan; section 8).

| Group | Profiles | Use |
| --- | --- | --- |
| At least 4 sermons | 33 | Part 1 (halves of at least 2 sermons) |
| At least 6 sermons | 20 | Part 1, reported separately (steadier halves) |
| At least 3 sermons | all with a sermon left after holding one out | Part 1b |
| Preachers at churches with several preachers, at least 3 sermons, and the church's other preachers with at least 3 sermons in all | 16 cases at 7 churches | Part 2 |

Same-church pairs in Part 1 (both at least 4 sermons): channel 15 (105, 111), channel 20 (60,
98, 102), channel 36 (77, 78). That gives 5 pairs, or **10 directional comparisons**: a small control,
read as a direction.

## 4. Steps and the technique used for each

| # | Step | Technique | Notes |
| --- | --- | --- | --- |
| 1 | Load preacher-window text per sermon | Existing loader and caption cleanup | Reuse, no change |
| 2 | Remove **channel boilerplate** | Near-duplicate detection: any 8-word sequence found in at least 30% of one channel's sermons (and at least 3 of them) marks its sentence as boilerplate | Removed sentences are kept for the baseline (step 6) |
| 3 | Remove **channel vocabulary** (Part 2 and the stripped runs) | Per channel, words used in at least half of that channel's sermons and in under 5% of other channels' sermons (church names, places, ministries, local series titles) | Lists are saved and shown in the report |
| 4 | Split each pastor in two (Part 1) | Code: sermons ordered by a fixed hash of the video id, alternated into halves A and B | Fixed and replayable |
| 5a | Fingerprint: **how they talk** | Stylometry: relative frequencies of the 300 most frequent words in the corpus, z-scored; **Burrows' Delta** (mean absolute z difference) | Pure Python. Mostly function words, so it is largely blind to topic |
| 5b | Fingerprint: **what they talk about** | Sentence embeddings with the local MiniLM encoder already in the repo (`collector_retrieval_encoder.py`, `sentence-transformers/all-MiniLM-L6-v2`, ONNX, CPU); about 200-word chunks, averaged per half or profile; cosine similarity | About 12k chunks, a few minutes on CPU. General-purpose model, not tuned for theology |
| 5c | Fingerprint: **where they sit theologically** | Reference-text scaling (Wordscores-style) on the same embeddings: axes from contrasting reference documents | **Deferred:** runs only after Brian approves the reference documents (section 9). Parts 1 and 2 report 5a and 5b first |
| 6 | **Channel-only baseline** | Steps 5a and 5b on the boilerplate and channel vocabulary removed in steps 2 and 3 | Shows how much matching channel habits alone can do |
| 7 | Match | Rank by distance (Delta for 5a, cosine for 5b) | One run per fingerprint |
| 8 | Explain | Per match, the words (5a) and the chunks nearest the other side (5b) that contribute most | So a match driven by a series topic or a church name is visible |

## 5. The three parts

### Part 1: distinctness

Each half A is ranked against all halves B in the group (33, and separately 20). Measures:
top-1 and top-3 accuracy, the right pastor's median rank, and, for the 10 same-church
comparisons, how often the right pastor beats the other preacher at the same church.

### Part 1b: identity pre-filter

Each sermon of a profile with at least 3 sermons is held out and ranked against every profile's
fingerprint built from that profile's other sermons (its own profile rebuilt without the held-out
sermon). Measure: share of sermons whose voice-assigned profile is in the text top 5. Labels
come from the existing voice-built profiles. Only voice-made assignments count as truth: if text
is later used in assignment, those assignments are never used to grade it.

### Part 2: church fit (on stripped text only)

For each of the 16 cases, the church is described by the fingerprint of the **other** preachers'
sermons on that channel. Candidates are all 47 profiles **except** those other preachers. Measure:
rank of the held-out preacher (chance median about 23; chance of top 5 about 11%). The run is
scored on text with boilerplate **and** channel vocabulary removed. The unstripped run and the
channel-only baseline are reported beside it to show how much leakage was removed.

This treats fit as similarity to the preachers a church already chose. A church looking for change
wants something else. Part 3 is where stated needs replace that assumption.

## 6. Pass marks, fixed before anything runs

| Part | Measure | Pass | Chance |
| --- | --- | --- | --- |
| 1 (33 profiles) | top-1 accuracy, best of 5a and 5b | at least 50%, and at least 20 points above the channel-only baseline | 3% |
| 1 (same church) | right pastor beats the same-church preacher | at least 8 of 10 | 5 of 10 |
| 1b | voice-assigned profile in text top 5 | at least 80% of held-out sermons | about 11% |
| 2 | held-out preacher in top 5, stripped text | at least 8 of 16, and median rank 5 or better | about 2 of 16 |

Readings:

- **Part 1 passes, including same church:** there is a repeatable pastor signal that cheap methods
  capture. Proceed to Part 2's reading, and design 5c.
- **Part 1 passes overall but fails same church:** the fingerprint mostly recognizes channels.
  Comparison needs pastors spread across channels before going further.
- **Part 1b passes:** text can cut voice comparisons by about 90% per new video (5 of 47; the real
  registry is larger, so recheck at scale). Adding it to `pte identity` would be a separate
  proposal.
- **Part 2 passes on stripped text:** the church's other preachers predict who it chose. That is
  evidence the fingerprint carries something a church selects on. **Fails:** similarity to the
  current preachers is not a fit signal at this depth. Fit then has to come from stated needs
  (Part 3).
- Any fail is reported as is. No feature, threshold, split or model change follows to rescue
  it; a second run needs a demonstrated defect and Brian's decision.

## 7. Part 3: church needs, mapped to techniques (draft for approval; no run)

Draft from typical search-committee criteria, since no real church questionnaire is available.
Brian edits or approves the list. Execution would be a later, separate spec.

| # | Need a church states | Answer from sermons? | Technique | Existing piece |
| --- | --- | --- | --- | --- |
| 1 | Theological alignment with our statement of faith | Partly | 5c reference axes using the church's own statement as one pole, plus need 2 | New (5c) |
| 2 | Positions on our distinctives (the church names 3 to 5, e.g. baptism, women in ministry, end times, Sabbath) | Yes, where preached | Embedding retrieval of passages on each distinctive, then **LLM** stance with speaker, polarity and qualifications | MiniLM retrieval; leaf-evidence v5 rules (31.2) |
| 3 | Expository or topical preaching | Yes | Scripture-use measures plus H style dimensions | `profile-scripture-usage`, H pack |
| 4 | Centrality of Scripture | Partly | Scripture-use benchmark, with its known caption and source limits | `reference-benchmarking.md` |
| 5 | How much politics from the pulpit, and how | Yes (attention and treatment, not party) | Jev `T:society_public_life` share plus P pack | Topic and P packs |
| 6 | Gospel and salvation emphasis | Yes | Jev S pack | S pack |
| 7 | Practical application and what listeners are asked to do | Yes | Jev L pack | L pack |
| 8 | Tone: comfort or challenge | Partly | H style plus L pack | H, L packs |
| 9 | Use of stories and personal illustration | Yes | Jev M pack | M pack |
| 10 | Sermon length | Yes | Sermon window duration | Existing metadata |
| — | Leadership, administration, pastoral care, character, family, availability, compensation | **No** | Not from sermons; shown as unknown | — |

Only need 2 uses an LLM, on retrieved passages, for a few questions per pastor. Everything else
reuses existing measurements or the cheap fingerprints. How a church supplies its needs (a short
questionnaire with distinctives and weights, its statement of faith, optionally its own channel)
is part of the later spec.

## 8. What this will not show, and known limits

- **"Talks like" is not "believes."** A match shows a distinctive pattern, not a position.
- **Speaker contamination remains.** Whole-service windows can include testimonies, children's
  stories and other leaders (31.6). The voice scan of whole services that would remove them is not
  feasible on current hardware and is deferred. Matches driven by such material show up in the
  step 8 explanation.
- **No dates.** Halves are not split by time, so a sermon series can fall in both halves and make
  matching easier. The step 8 explanation flags series-topic matches; this cannot be fully
  controlled.
- **Small controls.** 10 same-church comparisons and 16 church-fit cases give a direction, not
  proof, and nothing here establishes fit for thousands of pastors.
- **Population.** 47 analyzed profiles of 318. Results do not transfer to the larger registry
  until rerun there.

## 9. Decisions for Brian

1. Approve Parts 1, 1b and 2 with the pass marks of section 6 (5a and 5b only).
2. Approve, edit or replace the Part 3 needs list.
3. For 5c later: approve the reference documents. Proposal: published statements of faith of the
   traditions present in the corpus, plus, for Part 3, the church's own statement.
4. Confirm the outputs location: `<base>/evaluation/pastor-fit-v1/`.

## 10. Implementation sketch (after approval only)

- Module `src/pastor_transcript_extractor/pastor_fit/` with focused unit tests on synthetic text:
  boilerplate detection, channel vocabulary, Delta, split replay, ranking and the circularity rule.
- CLI under `pte analysis pastor-fit` (name checked against the generated CLI reference):
  `census` (eligible profiles and cases, no computation), `fingerprints`, `match` (Parts 1 and 1b),
  `church-fit` (Part 2), `report` (Markdown and JSON, project report format).
- Cost: $0 provider; local CPU, minutes. Brian runs `fingerprints`, `match` and `church-fit`
  (corpus-wide). One run per part; results are not rerun to improve them.
