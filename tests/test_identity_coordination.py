from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pastor_transcript_extractor.identity_coordination import (
    build_identity_coordination_report,
    count_missing_discovery_reviewed_constraints,
    load_discovery_acoustic_ranking_pairs,
    load_discovery_observation_states,
    load_discovery_resolution_pairs,
    load_shadow_association_confirmation_pairs,
    load_unmatched_association_fingerprints,
    write_identity_coordination_report,
)
from pastor_transcript_extractor.speaker_profile_discovery import (
    SHADOW_PROFILE_DISCOVERY_VERSION,
    TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    SHADOW_ASSOCIATION_VERSION,
)


class IdentityCoordinationTests(unittest.TestCase):
    def _association_payload(self) -> dict[str, object]:
        def comparison(fingerprint: str, margin: float) -> dict[str, object]:
            return {
                "exemplar_fingerprint": fingerprint,
                "outcome": "same_speaker",
                "reason": "approved_policy_same_band",
                "registry_mutation_allowed": False,
                "metrics": {
                    "cross": {
                        "p10": 0.60 + margin,
                        "median": 0.70 + margin,
                    }
                },
                "policy": {
                    "same_min_cross_p10": 0.60,
                    "same_min_cross_median": 0.70,
                },
            }

        payload: dict[str, object] = {
            "artifact_kind": "speaker_profile_shadow_association",
            "association_version": SHADOW_ASSOCIATION_VERSION,
            "shadow_mode": True,
            "registry_mutation_allowed": False,
            "automatic_assignment_allowed": False,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "candidate": {"input_fingerprint": "candidate"},
            "outcome": "proposed_match",
            "proposed_profile_id": 7,
            "profiles": [
                {
                    "profile_id": 7,
                    "meets_multi_exemplar_match": True,
                    "comparisons": [
                        comparison("exemplar-a", 0.08),
                        comparison("exemplar-b", 0.04),
                    ],
                }
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        return payload

    def _case(
        self,
        youtube_video_id: str,
        coverage_state: str,
        reason_code: str,
        *,
        observation_id: int | None = None,
        attempts: list[dict[str, object]] | None = None,
        profiles: list[int] | None = None,
    ) -> dict[str, object]:
        return {
            "video_id": int(youtube_video_id),
            "youtube_video_id": youtube_video_id,
            "extraction_result_id": int(youtube_video_id) + 100,
            "observation_id": observation_id,
            "observation_fingerprint": (
                f"observation-{observation_id}"
                if observation_id is not None
                else None
            ),
            "content_status": "accepted_sermon",
            "coverage_state": coverage_state,
            "accounted": coverage_state != "unaccounted",
            "reason_code": reason_code,
            "effective_profile_ids": profiles or [],
            "association_attempts": attempts or [],
        }

    def _audit(self, cases: list[dict[str, object]]) -> dict[str, object]:
        return {
            "artifact_kind": "speaker_association_coverage_audit",
            "audit_fingerprint": "audit",
            "cases": cases,
        }

    def test_report_assigns_one_actionable_state_per_extraction(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "1",
                        "associated",
                        "effective_profile_membership",
                        observation_id=1,
                        profiles=[57],
                    ),
                    self._case(
                        "2",
                        "unaccounted",
                        "association_attempt_missing",
                        observation_id=2,
                    ),
                    self._case(
                        "3",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=3,
                        attempts=[
                            {
                                "outcome": "insufficient_evidence",
                                "proposed_profile_id": None,
                            }
                        ],
                    ),
                    self._case(
                        "4",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=4,
                        attempts=[
                            {
                                "outcome": "proposed_match",
                                "proposed_profile_id": 58,
                            }
                        ],
                    ),
                ]
            )
        )

        self.assertEqual(
            {
                "associated": 1,
                "association_required": 1,
                "discovery_batch_candidate": 1,
                "profile_match_proposed": 1,
            },
            report["workflow_state_counts"],
        )
        self.assertEqual(1, report["counts"]["terminal"])
        self.assertEqual(3, report["counts"]["action_required"])
        self.assertFalse(report["registry_mutation_allowed"])

    def test_confirmation_candidate_takes_priority_over_generic_proposal(
        self,
    ) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "5",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=5,
                        attempts=[
                            {
                                "outcome": "proposed_match",
                                "proposed_profile_id": 65,
                            }
                        ],
                    )
                ]
            ),
            confirmation_observation_ids=[5],
        )

        case = report["cases"][0]
        self.assertEqual(
            "provisional_confirmation_proposed",
            case["workflow_state"],
        )
        self.assertEqual(
            "review_or_apply_provisional_confirmation",
            case["next_action"],
        )

    def test_single_video_filter_and_content_terminal(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "6",
                        "content_terminal",
                        "content_rejected",
                    ),
                    self._case(
                        "7",
                        "blocked",
                        "reviewed_invalid",
                        observation_id=7,
                    ),
                ]
            ),
            youtube_video_id="6",
        )

        self.assertEqual(1, report["counts"]["extractions"])
        self.assertEqual("content_terminal", report["cases"][0]["workflow_state"])
        self.assertTrue(report["cases"][0]["terminal"])

    def test_content_review_is_actionable_not_terminal(self) -> None:
        case = self._case(
            "9",
            "content_terminal",
            "content_review_required",
        )
        case["content_status"] = "review_required"

        report = build_identity_coordination_report(self._audit([case]))

        self.assertEqual(
            "content_review_required",
            report["cases"][0]["workflow_state"],
        )
        self.assertEqual("review_content", report["cases"][0]["next_action"])
        self.assertFalse(report["cases"][0]["terminal"])

    def test_discovery_history_avoids_redundant_batch_action(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "10",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=10,
                        attempts=[
                            {
                                "outcome": "insufficient_evidence",
                                "proposed_profile_id": None,
                            }
                        ],
                    )
                ]
            ),
            discovery_observation_states={10: "evaluated_unclustered"},
        )

        case = report["cases"][0]
        self.assertEqual(
            "identity_unresolved_waiting_for_evidence",
            case["workflow_state"],
        )
        self.assertEqual("await_new_evidence", case["next_action"])
        self.assertEqual(1, report["counts"]["waiting_for_evidence"])
        self.assertEqual(0, report["counts"]["action_required"])

    def test_exploratory_candidate_is_reported_as_human_review_action(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "10",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=10,
                    )
                ]
            ),
            discovery_observation_states={
                10: "exploratory_review_candidate"
            },
        )

        case = report["cases"][0]
        self.assertEqual(
            "identity_human_review_nominatable", case["workflow_state"]
        )
        self.assertEqual(
            "review_exploratory_profile_growth_pair", case["next_action"]
        )
        self.assertTrue(case["immediate_action_required"])

    def test_undersized_discovery_seed_waits_for_third_recording(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "16",
                        "evaluated",
                        "versioned_association_attempt",
                        observation_id=16,
                        attempts=[
                            {
                                "outcome": "no_match",
                                "proposed_profile_id": None,
                            }
                        ],
                    )
                ]
            ),
            discovery_observation_states={16: "undersized_component"},
        )

        case = report["cases"][0]
        self.assertEqual(
            "identity_unresolved_waiting_for_evidence",
            case["workflow_state"],
        )
        self.assertEqual("await_new_evidence", case["next_action"])
        self.assertFalse(case["immediate_action_required"])

    def test_discovery_state_loader_verifies_and_indexes_artifact(self) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {"observation_id": 11},
                {"observation_id": 12},
                {"observation_id": 13},
            ],
            "signature_failures": [{"observation_id": 14}],
            "pair_results": [
                {
                    "observation_ids": [11, 12],
                    "outcome": "insufficient_evidence",
                    "reason": "ambiguous_similarity",
                    "consistency_tier": "strong_strong",
                    "registry_mutation_allowed": False,
                    "metrics": {
                        "cross": {"p10": 0.59, "median": 0.78}
                    },
                    "policy": {
                        "same_min_cross_p10": 0.60,
                        "same_min_cross_median": 0.70,
                    },
                }
            ],
            "components": [
                {
                    "outcome": "blocked",
                    "members": [{"observation_id": 12}],
                },
                {
                    "outcome": "provisional_profile_candidate",
                    "members": [{"observation_id": 13}],
                },
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            states = load_discovery_observation_states(path)

        self.assertEqual(
            {
                11: "exploratory_review_candidate",
                12: "blocked_component",
                13: "provisional_component",
                14: "signature_failed",
            },
            states,
        )

    def test_discovery_resolution_loader_nominates_only_missing_overlap_edge(
        self,
    ) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {
                    "observation_id": observation_id,
                    "observation_fingerprint": fingerprint,
                }
                for observation_id, fingerprint in (
                    (21, "bridge-a"),
                    (22, "bridge-b"),
                    (23, "exclusive-left"),
                    (24, "exclusive-right"),
                )
            ],
            "signature_failures": [],
            "pair_results": [
                {
                    "observation_ids": [23, 24],
                    "outcome": "insufficient_evidence",
                }
            ],
            "components": [
                {
                    "component_id": "left-component",
                    "outcome": "blocked",
                    "blockers": ["overlapping_complete_link_components"],
                    "members": [
                        {"observation_id": value}
                        for value in (21, 22, 23)
                    ],
                },
                {
                    "component_id": "right-component",
                    "outcome": "blocked",
                    "blockers": ["overlapping_complete_link_components"],
                    "members": [
                        {"observation_id": value}
                        for value in (21, 22, 24)
                    ],
                },
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            resolutions = load_discovery_resolution_pairs(path)

        self.assertEqual(1, len(resolutions))
        resolution = resolutions[0]
        self.assertEqual(
            {"exclusive-left", "exclusive-right"},
            {resolution.fingerprint_a, resolution.fingerprint_b},
        )
        self.assertEqual(4, resolution.observations_unlocked)
        self.assertEqual(
            ("left-component", "right-component"),
            resolution.component_ids,
        )

    def test_discovery_acoustic_loader_keeps_safe_review_nominations(
        self,
    ) -> None:
        valid = {
            "observation_fingerprints": ["same-a", "same-b"],
            "outcome": "same_speaker",
            "reason": "approved_policy_same_band",
            "consistency_tier": "strong_strong",
            "registry_mutation_allowed": False,
            "retrieval_reasons": [
                "global_nearest_neighbor",
                "source_local_nearest_neighbor",
            ],
            "centroid_similarity": 0.94,
            "metrics": {"cross": {"p10": 0.72, "median": 0.78}},
            "policy": {
                "same_min_cross_p10": 0.60,
                "same_min_cross_median": 0.70,
            },
        }
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "pair_results": [
                valid,
                {
                    **valid,
                    "observation_fingerprints": [
                        "ambiguous-a",
                        "ambiguous-b",
                    ],
                    "outcome": "insufficient_evidence",
                    "reason": "ambiguous_similarity",
                    "centroid_similarity": 0.95,
                    "metrics": {
                        "cross": {"p10": 0.59, "median": 0.78}
                    },
                },
                {
                    **valid,
                    "observation_fingerprints": [
                        "deferred-a",
                        "deferred-b",
                    ],
                    "consistency_tier": "strong_deferred",
                },
                {
                    **valid,
                    "observation_fingerprints": [
                        "distant-a",
                        "distant-b",
                    ],
                    "outcome": "insufficient_evidence",
                    "reason": "ambiguous_similarity",
                    "centroid_similarity": 0.55,
                    "metrics": {
                        "cross": {"p10": 0.38, "median": 0.48}
                    },
                },
                {
                    **valid,
                    "observation_fingerprints": [
                        "reviewed-a",
                        "reviewed-b",
                    ],
                    "reviewed_constraint": True,
                },
            ],
            "components": [],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            rankings = load_discovery_acoustic_ranking_pairs(path)

        self.assertEqual(2, len(rankings))
        ranking = rankings[0]
        self.assertEqual(
            {"same-a", "same-b"},
            {ranking.fingerprint_a, ranking.fingerprint_b},
        )
        self.assertAlmostEqual(0.08, ranking.same_boundary_margin)
        self.assertEqual(0.94, ranking.centroid_similarity)
        self.assertTrue(ranking.source_local)
        self.assertIn(
            "source_local_nearest_neighbor",
            ranking.retrieval_reasons,
        )
        exploratory = rankings[1]
        self.assertEqual("insufficient_evidence", exploratory.outcome)
        self.assertEqual("ambiguous_similarity", exploratory.reason)
        self.assertAlmostEqual(-0.01, exploratory.same_boundary_margin)

    def test_discovery_constraint_freshness_detects_new_review(self) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {
                    "observation_id": 1,
                    "observation_fingerprint": "a",
                },
                {
                    "observation_id": 2,
                    "observation_fingerprint": "b",
                },
                {
                    "observation_id": 3,
                    "observation_fingerprint": "c",
                },
            ],
            "reviewed_constraints": {
                "same_speaker_observation_pairs": [[1, 2]],
                "different_speaker_observation_pairs": [],
            },
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            missing = count_missing_discovery_reviewed_constraints(
                path,
                {
                    frozenset(("a", "b")): "same_speaker",
                    frozenset(("b", "c")): "different_speaker",
                    frozenset(("outside", "c")): "same_speaker",
                },
            )

        self.assertEqual(1, missing)

    def test_association_loader_exposes_exact_multi_exemplar_same_edges(
        self,
    ) -> None:
        payload = self._association_payload()
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "association.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cache_path = Path(tempdir) / "cache.json"
            progress = []

            nominations = load_shadow_association_confirmation_pairs(
                (path,),
                progress_callback=lambda index, total, report_path: (
                    progress.append((index, total, report_path))
                ),
                cache_path=cache_path,
            )
            with patch(
                "pastor_transcript_extractor.identity_coordination."
                "_load_verified_association_report",
                side_effect=AssertionError("cache miss"),
            ):
                cached_nominations = (
                    load_shadow_association_confirmation_pairs(
                        (path,),
                        cache_path=cache_path,
                    )
                )

        self.assertEqual(2, len(nominations))
        self.assertEqual(
            {"exemplar-a", "exemplar-b"},
            {item.exemplar_fingerprint for item in nominations},
        )
        self.assertTrue(
            all(item.candidate_fingerprint == "candidate" for item in nominations)
        )
        self.assertTrue(all(item.same_comparison_count == 2 for item in nominations))
        self.assertAlmostEqual(0.08, nominations[0].same_boundary_margin)
        self.assertEqual([(1, 1, path.resolve())], progress)
        self.assertEqual(nominations, cached_nominations)

    def test_unmatched_association_loader_excludes_any_proposed_candidate(
        self,
    ) -> None:
        unmatched = self._association_payload()
        unmatched["candidate"] = {"input_fingerprint": "unmatched"}
        unmatched["outcome"] = "insufficient_evidence"
        unmatched["proposed_profile_id"] = None
        unmatched["result_sha256"] = _sha256(
            {key: value for key, value in unmatched.items() if key != "result_sha256"}
        )
        proposed = self._association_payload()
        second_unmatched = self._association_payload()
        second_unmatched["candidate"] = {"input_fingerprint": "candidate"}
        second_unmatched["outcome"] = "no_match"
        second_unmatched["proposed_profile_id"] = None
        second_unmatched["result_sha256"] = _sha256(
            {
                key: value
                for key, value in second_unmatched.items()
                if key != "result_sha256"
            }
        )
        with tempfile.TemporaryDirectory() as tempdir:
            paths = []
            for index, payload in enumerate(
                (unmatched, proposed, second_unmatched)
            ):
                path = Path(tempdir) / f"association-{index}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)

            fingerprints = load_unmatched_association_fingerprints(paths)

        self.assertEqual(frozenset(("unmatched",)), fingerprints)

    def test_association_loader_rejects_tampered_artifact(self) -> None:
        payload = self._association_payload()
        payload["outcome"] = "no_match"
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "association.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                load_shadow_association_confirmation_pairs((path,))

    def test_association_loader_ignores_stale_version(self) -> None:
        payload = self._association_payload()
        payload.pop("result_sha256")
        payload["association_version"] = "speaker_shadow_association_v2"
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "association.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            nominations = load_shadow_association_confirmation_pairs((path,))

        self.assertEqual((), nominations)

    def test_discovery_resolution_loader_exposes_near_same_frontier(self) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {
                    "observation_id": observation_id,
                    "observation_fingerprint": fingerprint,
                }
                for observation_id, fingerprint in (
                    (31, "near-a"),
                    (32, "near-b"),
                    (33, "anchor"),
                )
            ],
            "signature_failures": [],
            "pair_results": [],
            "review_frontier": [
                {
                    "observation_fingerprints": ["near-a", "near-b"],
                    "component_ids": ["blocked-component"],
                    "observations_unlocked": 3,
                    "same_boundary_distance": 0.01,
                }
            ],
            "components": [
                {
                    "component_id": "blocked-component",
                    "outcome": "blocked",
                    "blockers": ["component_not_complete_link"],
                    "members": [
                        {"observation_id": value} for value in (31, 32, 33)
                    ],
                }
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            resolutions = load_discovery_resolution_pairs(path)

        self.assertEqual(1, len(resolutions))
        self.assertEqual(
            "near_same_ambiguous_frontier", resolutions[0].resolution_kind
        )
        self.assertEqual(0.01, resolutions[0].same_boundary_distance)

    def test_discovery_resolution_loader_exposes_staged_bottleneck(self) -> None:
        payload = {
            "artifact_kind": "speaker_profile_shadow_discovery",
            "discovery_version": SHADOW_PROFILE_DISCOVERY_VERSION,
            "span_selection": {
                "version": TRANSCRIPT_GROUNDED_SPAN_SELECTION_VERSION,
            },
            "observation_signatures": [
                {
                    "observation_id": observation_id,
                    "observation_fingerprint": fingerprint,
                }
                for observation_id, fingerprint in (
                    (41, "seed-a"),
                    (42, "seed-b"),
                    (43, "candidate"),
                )
            ],
            "signature_failures": [],
            "pair_results": [],
            "review_frontier": [],
            "staged_review_frontier": [
                {
                    "component_ids": ["seed-component"],
                    "seed_observation_fingerprints": ["seed-a", "seed-b"],
                    "candidate_observation_fingerprint": "candidate",
                    "observations_unlocked": 3,
                    "required_review_count": 2,
                    "selected_review": {
                        "observation_fingerprints": ["candidate", "seed-b"],
                        "same_boundary_distance": 0.06,
                    },
                    "companion_review": {
                        "observation_fingerprints": ["candidate", "seed-a"],
                        "same_boundary_distance": 0.01,
                    },
                }
            ],
            "components": [
                {
                    "component_id": "seed-component",
                    "outcome": "blocked",
                    "members": [
                        {"observation_id": value} for value in (41, 42)
                    ],
                }
            ],
        }
        payload["result_sha256"] = _sha256(payload)
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "discovery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            resolutions = load_discovery_resolution_pairs(path)

        self.assertEqual(1, len(resolutions))
        resolution = resolutions[0]
        self.assertEqual(
            "staged_near_same_ambiguous_frontier", resolution.resolution_kind
        )
        self.assertEqual(("seed-a", "seed-b"), resolution.seed_fingerprints)
        self.assertEqual("candidate", resolution.candidate_fingerprint)
        self.assertEqual(
            ("candidate", "seed-a"), resolution.companion_pair_fingerprints
        )
        self.assertEqual(2, resolution.required_review_count)

    def test_report_write_is_content_addressed_and_replayable(self) -> None:
        report = build_identity_coordination_report(
            self._audit(
                [
                    self._case(
                        "8",
                        "unaccounted",
                        "association_attempt_missing",
                        observation_id=8,
                    )
                ]
            )
        )
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first = write_identity_coordination_report(root, report)
            second = write_identity_coordination_report(root, report)

            self.assertEqual(first, second)
            payload = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(
                report["coordination_fingerprint"],
                payload["coordination_fingerprint"],
            )
            self.assertIn("created_at", payload)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
