from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from pastor_transcript_extractor.identity_text_prefilter import TextStyleIndex
from pastor_transcript_extractor.identity_text_prefilter_check import (
    kept_credit,
    markdown,
    measure,
    select_queries,
    summarize,
    text_assisted_observations,
)

WORDS = ["the", "and", "of", "to", "we", "you", "that", "is", "in", "it", "so", "god"]


def style(seed: int, total: int = 1200) -> Counter:
    weights = [1 + ((index * (seed + 3)) % 7) for index in range(len(WORDS))]
    scale = total / sum(weights)
    return Counter({word: max(1, round(weight * scale)) for word, weight in zip(WORDS, weights)})


def row(better: int, ties: int = 0, ranked: int = 20, pool: int = 20, **extra) -> dict:
    return {"query_has_text": True, "better": better, "ties": ties, "ranked": ranked, "pool": pool,
            "other_recordings": 2, "pruned_exemplars_by_top": {"3": 0, "5": 0, "10": 0}, **extra}


class RecallArithmeticTests(unittest.TestCase):
    def test_kept_credit_with_ties(self) -> None:
        self.assertEqual(1.0, kept_credit(row(0), 1))
        self.assertEqual(0.0, kept_credit(row(5), 5))
        self.assertEqual(1.0, kept_credit(row(4), 5))
        # Two tied others at better=4: expected chance of being in the top 5 is 1/3.
        self.assertAlmostEqual(1 / 3, kept_credit(row(4, ties=2), 5))
        self.assertEqual(1.0, kept_credit({"assigned_profile_passes_through": True}, 1))

    def test_summary_shares_pruning_and_reach(self) -> None:
        rows = [row(0), row(2), row(6), row(12),
                {"query_has_text": True, "assigned_profile_passes_through": True, "ranked": 20, "pool": 21,
                 "other_recordings": 0, "pruned_exemplars_by_top": {"3": 0, "5": 0, "10": 0}},
                {"query_has_text": False, "ranked": 0, "pool": 20, "other_recordings": 2}]
        s = summarize(rows, (3, 5, 10))
        self.assertEqual(6, s["observations"])
        self.assertEqual(5, s["observations_with_usable_text"])
        self.assertEqual(1, s["assigned_profile_passes_through"])
        top5 = s["per_top"]["5"]
        self.assertAlmostEqual(2 / 4, top5["kept_share_assigned_profile_has_text"])
        self.assertAlmostEqual(3 / 5, top5["kept_share"])
        self.assertEqual(5 * 15, top5["pruned_profile_comparisons"])
        self.assertEqual(4 * 20 + 21, top5["pool_profile_comparisons"])
        self.assertAlmostEqual((101 - 75) / 5, top5["mean_profiles_kept_per_observation"])
        self.assertAlmostEqual(3 / 4, s["per_top"]["10"]["kept_share_assigned_profile_has_text"])
        # 95% of the four ranked cases needs all four: rank 13 means N = 13.
        self.assertEqual(13, s["smallest_top_reaching_95_percent"])
        self.assertFalse(s["meets_default_on_bar"])
        self.assertEqual(5.0, s["median_expected_rank"])  # ranks 1, 3, 7, 13
        self.assertTrue(summarize([row(0)] * 19 + [row(9)], (5,))["meets_default_on_bar"])


class SelectionTests(unittest.TestCase):
    def test_one_query_per_video_and_exclusions(self) -> None:
        labels = {1: {10}, 2: {10}, 3: {20}, 4: {30}, 5: {40}, 6: {50}, 7: {60}}
        videos = {1: 100, 2: 100, 3: 101, 4: 101, 5: 102, 6: 103}
        queries, counts = select_queries(labels, videos, excluded={6})
        self.assertEqual({2: 10, 5: 40}, queries)  # latest observation of video 100; video 101 conflicts
        self.assertEqual(1, counts["videos_with_conflicting_labels"])
        self.assertEqual(1, counts["excluded_text_assisted"])
        self.assertEqual(1, counts["labeled_observation_missing"])

    def test_text_assisted_reports_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "aaaaaaaaaaaaaaaa").mkdir()
            (root / "aaaaaaaaaaaaaaaa" / "r.json").write_text(json.dumps({"routing": {"text_prefilter": {}}}))
            (root / "bbbbbbbbbbbbbbbb").mkdir()
            (root / "bbbbbbbbbbbbbbbb" / "r.json").write_text(json.dumps({"routing": {"route": "x"}}))
            machine = root / "elsewhere.json"
            machine.write_text(json.dumps({"routing": {"text_prefilter": {"top": 5}}}))
            flagged = text_assisted_observations(
                {1: "a" * 64, 2: "b" * 64, 3: "c" * 64}, root, {3: [str(machine)]})
            self.assertEqual({1, 3}, flagged)


class MeasureTests(unittest.TestCase):
    def test_pool_holds_only_profiles_large_enough_for_voice_matching(self) -> None:
        # Profiles 1 and 2 have four recordings; profile 3 has two and is never in the pool.
        queries = {10 * k + i: k for k in (1, 2) for i in range(1, 5)}
        queries.update({31: 3, 32: 3})
        counts = {o: style(p) for o, p in queries.items()}
        # Profile 3's text is a copy of profile 1's, so in v1 it would compete with profile 1.
        counts[31] = counts[32] = style(1)
        index = TextStyleIndex(counts, {o: o for o in counts})
        result = measure(index, queries, (1,), minimum_pool_recordings=3)
        rows = {r["observation_id"]: r for r in result["rows"]}
        self.assertNotIn(31, rows)
        self.assertNotIn(32, rows)
        self.assertEqual(2, result["summary"]["assigned_profile_below_pool_minimum"])
        for observation_id in (11, 12, 13, 14):
            self.assertEqual(2, rows[observation_id]["ranked"])
            self.assertEqual(0, rows[observation_id]["better"] + rows[observation_id]["ties"])

    def test_measure_ranks_with_leave_one_out(self) -> None:
        # Four speakers, two videos each; observation id 10k + i, video id = observation id.
        queries = {10 * k + i: k for k in range(1, 5) for i in (1, 2)}
        queries[61] = 6  # a one-recording profile: passes through when it is the query
        counts = {o: style(p) for o, p in queries.items()}
        index = TextStyleIndex(counts, {o: o for o in counts})
        result = measure(index, queries, (1, 3), minimum_pool_recordings=0)  # v1: every profile
        rows = {r["observation_id"]: r for r in result["rows"]}
        self.assertTrue(rows[61]["assigned_profile_passes_through"])
        for observation_id in (11, 12, 21, 22, 31, 32, 41, 42):
            self.assertEqual(0, rows[observation_id]["better"])
        summary = result["summary"]
        self.assertEqual(1.0, summary["per_top"]["1"]["kept_share_assigned_profile_has_text"])
        self.assertEqual(1, summary["smallest_top_reaching_95_percent"])
        self.assertTrue(summary["meets_default_on_bar"])
        report = {"scorer": {"version": "v", "style_words": 300}, "summary": summary,
                  "population": {"registry_profiles_with_labeled_recordings": 5, "labeled_observations": 9,
                                 "queried_videos": 9, "label_sources": {}, "minimum_usable_words": 500},
                  "circularity": {"rule": "r", "text_assisted_observations_excluded": 0}}
        text = markdown(report)
        self.assertIn("Meets the bar", text)
        self.assertIn("| 5 |", text)


if __name__ == "__main__":
    unittest.main()
