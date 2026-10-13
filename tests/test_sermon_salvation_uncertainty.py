"""Focused numerical and freshness contracts; no dataset or provider work."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pastor_transcript_extractor.sermon_salvation_convergence import _hash, collect_cohort_measurements
from pastor_transcript_extractor.sermon_salvation_relationships import SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS
from pastor_transcript_extractor.sermon_salvation_uncertainty import build_uncertainty, write_uncertainty


def inputs():
    proposal = {"policy_version": "salvation-exact-cohort-proposal-v3-diversity", "provider_requests": 0,
                "pastors": [{"profile_id": 80, "display_name": "Test pastor",
                             "included": [{"video_id": i} for i in range(1, 5)]}]}
    proposal["input_fingerprint"] = _hash({key: value for key, value in proposal.items() if key != "provider_requests"})
    sermons = []
    for i, value in enumerate([0.0, 0.2, 0.4, 0.0], 1):
        sermons.append({"video_id": i, "baseline": i <= 3, "routed_block_count": 5 if i < 4 else 0,
                        "measurement_status": "measured" if i < 4 else "zero_routed_blocks",
                        "period_key": "first" if i <= 2 else None, "series_key": "series" if i <= 2 else None,
                        "source_artifact_sha256": str(i), "topic_artifact_sha256": str(i),
                        "projected_artifact_sha256": str(i),
                        "relationships": {leaf: {"routed_block_fraction": value, "observed": value > 0}
                                          for leaf in SALVATION_RELATIONSHIP_OBSERVATION_THRESHOLDS}})
    return proposal, {80: sermons}


class UncertaintyTests(unittest.TestCase):
    def test_known_omission_checkpoint_and_denominator_values(self):
        proposal, sermons = inputs()
        original = deepcopy(sermons)
        report = build_uncertainty(proposal, sermons)
        self.assertEqual(sermons, original)
        self.assertEqual(report, build_uncertainty(proposal, sermons))
        pastor = report["pastors"][0]
        self.assertEqual(pastor["missing_period_provenance"], 2)
        leaf = next(iter(pastor["relationships"].values()))
        self.assertEqual(leaf["positive_sermon_ids"], [2, 3])
        self.assertEqual(leaf["full_available_equal_sermon_mean"], 0.15)
        self.assertEqual(leaf["leave_one_sermon_out"]["minimum"], 0.066667)
        self.assertEqual(leaf["leave_one_sermon_out"]["maximum"], 0.2)
        self.assertEqual(leaf["checkpoints"][1]["signed_delta_from_previous"], -0.05)
        self.assertEqual(leaf["denominator_sensitivity"]["conditional_routed_mean"], 0.2)
        self.assertEqual(leaf["denominator_sensitivity"]["conditional_routed_sermons"], 3)
        self.assertFalse(report["pastor_level_sufficiency_granted"])
        self.assertEqual(report["provider_requests"], 0)

    def test_all_zero_routes_are_unavailable_conditionally_not_absence(self):
        proposal, sermons = inputs()
        for sermon in sermons[80]:
            sermon.update(routed_block_count=0, measurement_status="zero_routed_blocks")
            for leaf in sermon["relationships"].values():
                leaf.update(routed_block_fraction=0.0, observed=False)
        report = build_uncertainty(proposal, sermons)
        for leaf in report["pastors"][0]["relationships"].values():
            self.assertEqual(leaf["evidence_status"], "insufficient_positive_evidence")
            self.assertIsNone(leaf["denominator_sensitivity"]["conditional_routed_mean"])
            self.assertEqual(leaf["leave_one_sermon_out"]["maximum"], 0)

    def test_missing_leaf_evidence_stays_out_of_denominators(self):
        proposal, sermons = inputs()
        sermons[80][-1] = {"video_id": 4, "measurement_status": "unavailable_missing_cached_leaf_artifact"}
        report = build_uncertainty(proposal, sermons)
        leaf = next(iter(report["pastors"][0]["relationships"].values()))
        self.assertEqual(leaf["denominator_sensitivity"]["primary_sermons"], 3)
        self.assertEqual(leaf["full_available_equal_sermon_mean"], 0.2)
        self.assertEqual(leaf["checkpoints"][1]["status"], "unavailable_insufficient_measured_sermons")

    def test_write_reuses_exact_artifacts_and_repairs_corruption(self):
        proposal, sermons = inputs()
        report = build_uncertainty(proposal, sermons)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "uncertainty.json"
            _, markdown, reused = write_uncertainty(path, report)
            self.assertFalse(reused)
            stamp = path.stat().st_mtime_ns
            self.assertTrue(write_uncertainty(path, report)[2])
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            damaged = deepcopy(report)
            damaged["pastors"] = []
            path.write_text(json.dumps(damaged))
            self.assertFalse(write_uncertainty(path, report)[2])
            self.assertIn("Leave-one-out ranges", markdown.read_text())
            self.assertIn("unknown period/series counts: 2/2", markdown.read_text())

    def test_measurement_cache_reuses_then_invalidates_every_source(self):
        proposal, sermons = inputs()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / "app.db"
            db.write_text("db")
            source = root / "classification.json"
            source.write_text("{}")
            cache = root / "cache.json"
            database = SimpleNamespace(database_path=db, get_video_by_id=lambda _: object())
            now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
            for sermon in sermons[80]:
                sermon["classification_path"] = str(source)
            def load(database, row, profile_id, **kwargs):
                return deepcopy(sermons[80][int(row["video_id"]) - 1])
            module = "pastor_transcript_extractor.sermon_salvation_convergence"
            with (patch(module + ".assess_topic_profile_projection", return_value=SimpleNamespace(source_path=str(source))),
                  patch(module + "._load_sermon", side_effect=load) as loader):
                measured, hit = collect_cohort_measurements(database, proposal, cache, now)
                self.assertFalse(hit)
                self.assertEqual(loader.call_count, 4)
                self.assertTrue(collect_cohort_measurements(database, proposal, cache, now)[1])
                self.assertEqual(loader.call_count, 4)
                source.write_text("changed classification")
                self.assertFalse(collect_cohort_measurements(database, proposal, cache, now)[1])
                Path(str(db) + "-wal").write_text("changed WAL")
                self.assertFalse(collect_cohort_measurements(database, proposal, cache, now)[1])
                db.write_text("changed database")
                self.assertFalse(collect_cohort_measurements(database, proposal, cache, now)[1])
                self.assertFalse(collect_cohort_measurements(database, proposal, cache, now + timedelta(hours=1))[1])
                payload = json.loads(cache.read_text())
                payload["sermons_by_profile"]["80"][0]["baseline"] = False
                cache.write_text(json.dumps(payload))
                self.assertFalse(collect_cohort_measurements(database, proposal, cache, now)[1])
                with patch(module + ".salvation_relationship_pack_digest", return_value="new pack"):
                    self.assertFalse(collect_cohort_measurements(database, proposal, cache, now)[1])
                changed = deepcopy(proposal)
                changed["pastors"][0]["display_name"] = "Changed frozen input"
                changed["input_fingerprint"] = _hash({key: value for key, value in changed.items()
                                                       if key not in {"input_fingerprint", "provider_requests"}})
                self.assertFalse(collect_cohort_measurements(database, changed, cache, now)[1])
                self.assertEqual(measured, sermons)

    def test_changed_source_during_collection_rejected_without_cache_write(self):
        proposal, sermons = inputs()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / "app.db"
            source = root / "classification.json"
            db.write_text("db")
            source.write_text("{}")
            cache = root / "cache.json"
            database = SimpleNamespace(database_path=db, get_video_by_id=lambda _: object())
            def load(*args, **kwargs):
                source.write_text("changed while reading")
                return {**sermons[80][0], "classification_path": str(source)}
            module = "pastor_transcript_extractor.sermon_salvation_convergence"
            with (patch(module + ".assess_topic_profile_projection", return_value=SimpleNamespace(source_path=str(source))),
                  patch(module + "._load_sermon", side_effect=load)):
                with self.assertRaisesRegex(ValueError, "changed"):
                    collect_cohort_measurements(database, proposal, cache)
            self.assertFalse(cache.exists())


if __name__ == "__main__":
    unittest.main()
