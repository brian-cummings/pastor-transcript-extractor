# E1a falsification handoff

The first audit tests whether transcript representation materially changes the two leading literal Scripture measures. Use **two to four distinct sermons**, starting with run 145 plus an independently selected case. Record why each was selected. Passing this small audit means only “not falsified in the selected cases.” It does not certify a feature, establish population precision or permit pastor ranking.

The packet and manifest infrastructure is reusable for E1b. Listening, correcting and double-reviewing the full 12-sermon sample is the substantial incremental cost, so that work follows the targeted E1a audit.

## 1. Export saved inputs

Run from `/Users/briancummings/code/pastor-transcript-extractor`. This exact command reads one saved run and exports its evidence; it performs no analysis or database writes:

```bash
.venv/bin/python -m pastor_transcript_extractor.analytical_pilot export \
  --database /Users/briancummings/Documents/PastorSearchData/app.db \
  --run-id 145 \
  --output /Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a/run-145.json
```

Choose a second existing Scripture run independently, preferably a different caption method/pastor. Repeat the export command with that real run ID and an output filename of `second.json` in the same directory. Do not create new corpus analyses just to populate the audit. If export says the source no longer matches the saved run, stop and locate the matching historical artifact; do not relabel current content as the old input.

## 2. Freeze the design before review

The command below assumes the second export is named `second.json`. Replace the rationale with the actual reason for selecting that case. The IQRs are rounded historical snapshot-2 values from the review, used only as declared fixed scales: density 3.0281−1.5348=1.4933; text-span fraction .0237−.0109=.0128. Choose practical tolerances before examining corrected results. The .25-IQR limit is an illustrative E1a per-sermon falsification bound, not E1b's distributional gate.

```bash
.venv/bin/python -m pastor_transcript_extractor.analytical_pilot freeze \
  --packet /Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a/run-145.json \
  --packet /Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a/second.json \
  --density-iqr 1.4933 \
  --span-iqr 0.0128 \
  --maximum-shift-iqr 0.25 \
  --scale-source 'Historical population snapshot 2; rounded IQRs from REVIEW.md; not new calibration' \
  --rationale 'Run 145: known rolling-caption case. Second case: REPLACE WITH SELECTION REASON.' \
  --output /Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a/manifest.json
```

You may add one or two further `--packet` arguments before freezing. A second run of the same original video cannot count as a second sermon. Keep the frozen manifest and packet `original` sections unchanged. The report records the manifest hash, full policy and reviewed packet hashes.

## 3. Complete the human review

Edit only each packet's `review` object. Audio review is required; another detector pass is not ground truth.

- Set `profile_id` to the reviewed profile identity, `reviewer`, `reviewed_at` in `YYYY-MM-DD` format, and the actual `transcript_method`. Record date, series, passage/topic, translation and notes when verified; E1a permits unknown date/series metadata and makes no claims based on them.
- Confirm `identity_verified`, `audio_checked`, `boundaries_verified` and `whole_sermon_reviewed` only after completing those checks. Set `status` to `reviewed` last.
- Correct `segments` to the audio, preserving legitimate spoken repetition. Keep sequential `index` values starting at zero. Every segment needs source segment indexes and valid timestamps within the frozen sermon window. Keep the original window fixed to isolate representation; investigate boundary corrections separately.
- Map every original segment to reviewed text or list it in `removed_source_segments` with its index and an audio-grounded removal reason. Removing a repeated caption does not mean removing a second citation actually spoken by the preacher.
- Add every citation episode, including citations missed by the detector, to `citation_episodes`. Each entry needs `episode_id`, `canonical_reference`, `source_segment_indexes`, `start_seconds` and `end_seconds`.
- Complete every `citation_adjudications` row exactly once. Use `episode` for a detected spoken event, `duplicate_caption` for a redundant caption detection of an existing episode, or `spurious` with a null episode ID for a false detection. Matching/duplicate detections must name an episode in the reviewed catalog. Assign a distinct episode ID for each genuine spoken repetition.

Example episode and adjudications:

```json
{
  "citation_episodes": [
    {"episode_id": "e1", "canonical_reference": "Romans 3:24",
     "source_segment_indexes": [1683, 1684, 1685],
     "start_seconds": 1972.559, "end_seconds": 1979.029}
  ],
  "citation_adjudications": [
    {"evidence_id": 123, "judgment": "episode", "episode_id": "e1"},
    {"evidence_id": 124, "judgment": "duplicate_caption", "episode_id": "e1"}
  ]
}
```

The evidence IDs above are illustrative: use the actual IDs already exported in your packet. The timestamps illustrate the review's cited caption region; verify episode boundaries against audio. The optional `reviewed_text_spans` field is reserved for E1b and is **not evaluated** by E1a. Current E1a compares detected span fractions across representations; it does not measure alignment accuracy against fully reviewed ground-truth spans.

## 4. Brian runs the bounded audit

After the frozen packets are reviewed:

```bash
.venv/bin/python -m pastor_transcript_extractor.analytical_pilot evaluate \
  /Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a/manifest.json \
  --output /Users/briancummings/Documents/PastorSearchData/analytical-pilot/e1a/report.json
```

This runs only the original/reviewed pairs explicitly named in the manifest. It uses the shared production Scripture detectors, verifies original-count reconstruction, and writes no database records. It refuses to overwrite the report. The agent does not run or monitor this dataset audit.

Inspect each feature's outcome and the per-sermon signed shifts, absolute IQR shifts and citation audit. `distinct_episode_precision` counts distinct recovered episodes divided by detected mentions, so duplicate caption detections reduce it. It is a selected-sermon audit statistic, with no claimed corpus uncertainty bound. `episode_recall` includes independently reviewed missed episodes in its denominator.

A counterexample motivates repair or narrowing the affected measurement before expansion. Unchanged ratios do not dismiss duplicate-event errors: duplication can cancel in ratios. If no material counterexample emerges, decide whether the signal warrants E1b's 12-sermon independent review and uncertainty estimation. E1b certification and E2 cross-series validation are not implemented or implied by this command.

## Development verification

Focused unit tests only; no corpus reclassification, backfill or dataset evaluation:

```bash
.venv/bin/python -m unittest \
  tests.test_analytical_pilot tests.test_population_analysis \
  tests.test_benchmark tests.test_style_analysis -q
```

New population reports use `scripture-population-report@2`, with deletion sensitivity and cohort labels. New benchmark snapshots use `reference-panel-snapshot@4` / `benchmark-feature-schema@3`. Old artifacts remain inspectable, but new comparisons require rebuilding their snapshot under the new schema. Default comparison scope is fixed at `core`; `--comparison-level full` is explicit. `--historical-references --snapshot-id ID` permits pinned reference inputs of the new schema with a current candidate. It does not rerun the old algorithm or certify the comparison.
