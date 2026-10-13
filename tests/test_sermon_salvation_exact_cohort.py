from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from pastor_transcript_extractor.sermon_salvation_exact_cohort import (
    _pair_evidence,
    _shingles,
    build_exact_cohort_proposal,
    collect_exact_cohort_evidence,
    write_exact_cohort_proposal,
)


class ExactCohortTests(unittest.TestCase):
    def test_matching_title_needs_transcript_evidence(self) -> None:
        inventory = {"pastors": [{"profile_id": 117, "candidates": [
            {"video_id": 1, "title": "Same title"},
            {"video_id": 2, "title": "Same title"},
        ]}]}
        source = {video_id: {"artifact_provenance": {"source_audio_sha256": []},
                             "transcript_sha256": str(video_id), "source_period_key": None}
                  for video_id in [1, 2]}
        pairs = _pair_evidence(inventory, source, {1: _shingles("alpha beta gamma delta epsilon zeta"),
                                                  2: _shingles("one two three four five six")})
        self.assertEqual("same_title_unresolved", pairs[0]["decision"])
        self.assertEqual(0, pairs[0]["shared_5_word_shingles"])

    def test_baselines_remain_and_shortfalls_are_explicit(self) -> None:
        pastors = []
        cohort_pastors = []
        source = {}
        for profile_id in (117, 80, 130):
            candidates = []
            for n in range(1, 13):
                video_id = profile_id * 100 + n
                candidates.append({"video_id": video_id, "title": f"Title {n}",
                                   "eligible_block_count": n})
                source[str(video_id)] = {"source_period_key": None,
                                         "source_period_evidence": None,
                                         "source_series_name": None,
                                         "source_series_evidence": None,
                                         "transcript_sha256": str(video_id),
                                         "artifact_provenance": {"transcript": {}, "metadata": {}}}
            pastors.append({"profile_id": profile_id, "display_name": f"Pastor {profile_id}",
                            "baseline_video_ids": [profile_id * 100 + n for n in (1, 2, 3)],
                            "candidates": candidates})
            cohort_pastors.append({"sermons": [{"video_id": profile_id * 100 + n,
                                                "period_key": "2026-h1" if n < 3 else "2026-h2",
                                                "period_evidence": {"source_kind": "reviewed"},
                                                "series_key": f"series-{n}"} for n in (1, 2, 3)]})
        inventory = {"input_fingerprint": "i", "pastors": pastors}
        cohort = {"cohort_sha256": "c", "pastors": cohort_pastors}
        evidence = {"artifact_fingerprint": "a", "source": source,
                    "pairs": [{"profile_id": 117, "video_ids": [11704, 11705],
                               "decision": "same_title_unresolved"}]}
        report = build_exact_cohort_proposal(inventory, cohort, evidence)
        ryd = report["pastors"][0]
        self.assertEqual([11701, 11702, 11703], ryd["baseline_video_ids"])
        self.assertEqual(11, len(ryd["included"]))
        self.assertEqual(1, ryd["shortfalls"]["independent_sermons"])
        self.assertEqual("equivalence_group_alternate", ryd["excluded"][0]["reason"])
        self.assertEqual("contract_shortfall_review_required", report["status"])
        self.assertFalse(report["analytical_credit_granted"])
        self.assertEqual(0, report["provider_requests"])
        reviewed = build_exact_cohort_proposal(inventory, cohort, evidence, {
            "inventory_fingerprint": "i", "cohort_sha256": "c",
            "pair_adjudications": {"11704-11705": {
                "decision": "same_sermon_split", "evidence": [{"source_kind": "transcript_boundary"}]}},
        })
        self.assertEqual("confirmed_same_sermon_split",
                         next(group for group in reviewed["pastors"][0]["equivalence_groups"]
                              if len(group["video_ids"]) > 1)["status"])
        self.assertEqual(0, reviewed["pastors"][0]["shortfalls"]["unresolved_equivalence_groups"])

        evidence["pairs"] = []
        for profile_id in (117, 80, 130):
            for number, (series, period) in enumerate(
                [("series 1", "2026-h1"), ("series 2", "2026-h2"),
                 ("series 3", "2026-h2")], start=4
            ):
                item = source[str(profile_id * 100 + number)]
                item["source_series_name"] = series
                item["source_series_evidence"] = {"source_kind": "description"}
                item["source_period_key"] = period
                item["source_period_evidence"] = {"source_kind": "upload_date"}
        complete = build_exact_cohort_proposal(inventory, cohort, evidence)
        self.assertEqual("bounded_approval_ready", complete["status"])
        self.assertTrue(all(item["contract_satisfied"] for item in complete["pastors"]))
        self.assertGreater(complete["pastors"][0]["shortfalls"]["missing_series_provenance"], 0)

        # One replicated series is enough when 12 independent sermons span
        # two replicated periods and the largest known series stays at half.
        for profile_id in (117, 80, 130):
            for number in range(4, 13):
                item = source[str(profile_id * 100 + number)]
                item["source_period_key"] = "2026-h1" if number <= 6 else "2026-h2"
                item["source_period_evidence"] = {"source_kind": "upload_date"}
                item["source_series_name"] = "series 1" if number <= 8 else None
                item["source_series_evidence"] = ({"source_kind": "description"}
                                                   if number <= 8 else None)
        diverse = build_exact_cohort_proposal(inventory, cohort, evidence)
        self.assertEqual("bounded_approval_ready", diverse["status"])
        self.assertEqual(1, diverse["pastors"][0]["replicated_series_count"])
        self.assertEqual(6, diverse["pastors"][0]["largest_documented_series"]["sermons"])
        self.assertGreater(diverse["pastors"][0]["shortfalls"]["missing_series_provenance"], 0)

        for profile_id in (117, 80, 130):
            item = source[str(profile_id * 100 + 9)]
            item["source_series_name"] = "series 1"
            item["source_series_evidence"] = {"source_kind": "description"}
        dominated = build_exact_cohort_proposal(inventory, cohort, evidence)
        self.assertEqual("contract_shortfall_review_required", dominated["status"])
        self.assertIn("documented_series_concentration", dominated["pastors"][0]["contract_blockers"])

        with TemporaryDirectory() as directory:
            output = Path(directory) / "proposal.json"
            _, markdown, reused = write_exact_cohort_proposal(output, diverse)
            self.assertFalse(reused)
            _, _, reused = write_exact_cohort_proposal(output, diverse)
            self.assertTrue(reused)
            markdown.write_text("stale render", encoding="utf-8")
            _, _, reused = write_exact_cohort_proposal(output, diverse)
            self.assertFalse(reused)
            self.assertIn("Series diversity:", markdown.read_text(encoding="utf-8"))

    def test_artifact_cache_reuses_unchanged_bounded_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "transcript.txt"
            transcript.write_text("alpha beta gamma delta epsilon zeta", encoding="utf-8")
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"raw_metadata": {"upload_date": "20260808",
                                                          "description": "Part 2 of the Series: Example. By Pastor"}}),
                                encoding="utf-8")
            database = Mock()
            database.list_transcript_artifacts_for_video.return_value = [Mock(
                id=3, raw_text_path=str(transcript), content_sha256=None,
                superseded_by_artifact_id=None, artifact_kind="canonical")]
            database.get_latest_metadata_artifact_for_video.return_value = Mock(
                id=4, source_kind="yt_dlp_full_video", artifact_path=str(metadata),
                content_sha256="m")
            database.list_media_artifacts_for_video.return_value = []
            inventory = {"input_fingerprint": "i", "pastors": [
                {"profile_id": 117, "candidates": [{"video_id": 1, "title": "Example"}]}]}
            cache_path = root / "evidence.json"
            first, hit = collect_exact_cohort_evidence(database, inventory, cache_path)
            self.assertFalse(hit)
            self.assertEqual("2026-h2", first["source"][1]["source_period_key"])
            second, hit = collect_exact_cohort_evidence(database, inventory, cache_path)
            self.assertTrue(hit)
            self.assertEqual(first["artifact_fingerprint"], second["artifact_fingerprint"])
            inventory["pastors"][0]["candidates"][0]["title"] = "Changed title"
            third, hit = collect_exact_cohort_evidence(database, inventory, cache_path)
            self.assertFalse(hit)
            self.assertNotEqual(first["artifact_fingerprint"], third["artifact_fingerprint"])


if __name__ == "__main__":
    unittest.main()
