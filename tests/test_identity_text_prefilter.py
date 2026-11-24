from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import unittest

from pastor_transcript_extractor.identity_text_prefilter import (
    MINIMUM_USABLE_WORDS,
    TEXT_PREFILTER_VERSION,
    TextStyleIndex,
    decide,
)
from pastor_transcript_extractor.speaker_shadow_association import (
    ProfileAssociationReadiness,
    ShadowExemplar,
    select_staged_association_profiles,
)
from pastor_transcript_extractor.workflows.identity.association import (
    ShadowAssociationRequest,
    plan_association_preparation_scope,
    plan_association_profile_route,
)

WORDS = ["the", "and", "of", "to", "we", "you", "that", "is", "in", "it", "so", "god"]


def style(seed: int, total: int = 1200) -> Counter:
    """A fixed word distribution per speaker; different seeds favor different words."""
    weights = [1 + ((index * (seed + 3)) % 7) for index in range(len(WORDS))]
    scale = total / sum(weights)
    return Counter({word: max(1, round(weight * scale)) for word, weight in zip(WORDS, weights)})


def index_for(profiles: dict[int, list[int]], seeds: dict[int, int], extra: dict[int, Counter] | None = None,
              videos: dict[int, int] | None = None) -> TextStyleIndex:
    counts = {o: style(seeds[o]) for members in profiles.values() for o in members if o in seeds}
    counts.update(extra or {})
    return TextStyleIndex(counts, videos or {o: o for o in counts})


class TextRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        # Profiles 1..4, two recordings each; speaker k's recordings share seed k.
        self.profiles = {k: [10 * k + 1, 10 * k + 2] for k in range(1, 5)}
        self.seeds = {o: k for k, members in self.profiles.items() for o in members}
        self.seeds[99] = 3  # the candidate talks like speaker 3

    def index(self, **kwargs) -> TextStyleIndex:
        extra = {99: style(3)}
        extra.update(kwargs.pop("extra", {}))
        return index_for(self.profiles, self.seeds, extra=extra, **kwargs)

    def test_closest_profile_ranks_first(self) -> None:
        ranking = self.index().rank(99, self.profiles)
        self.assertTrue(ranking.query_has_text)
        self.assertEqual(3, ranking.ranked[0][0])
        self.assertEqual(4, len(ranking.ranked))
        self.assertEqual((), ranking.pass_through_profile_ids)

    def test_decide_keeps_top_n_and_prunes_the_rest(self) -> None:
        decision = decide(self.index().rank(99, self.profiles), 2)
        self.assertEqual(3, decision.kept_profile_ids[0])
        self.assertEqual(2, len(decision.kept_profile_ids))
        self.assertEqual(2, len(decision.pruned_profile_ids))
        self.assertNotIn(3, decision.pruned_profile_ids)
        self.assertEqual(set(self.profiles), set(decision.kept_profile_ids) | decision.pruned_profile_ids)
        self.assertEqual(frozenset(), decide(self.index().rank(99, self.profiles), 10).pruned_profile_ids)
        with self.assertRaises(ValueError):
            decide(self.index().rank(99, self.profiles), 0)

    def test_profile_without_usable_text_is_never_pruned(self) -> None:
        profiles = dict(self.profiles)
        profiles[5] = [51]  # a profile whose only recording is too short to use
        short = Counter({"the": MINIMUM_USABLE_WORDS - 1})
        index = index_for(profiles, self.seeds, extra={99: style(3), 51: short})
        decision = decide(index.rank(99, profiles), 1)
        self.assertIn(5, decision.pass_through_profile_ids)
        self.assertIn(5, decision.kept_profile_ids)
        self.assertNotIn(5, decision.pruned_profile_ids)
        profiles[6] = [61]  # a profile with no extraction text at all
        decision = decide(index.rank(99, profiles), 1)
        self.assertIn(6, decision.kept_profile_ids)
        self.assertNotIn(6, decision.pruned_profile_ids)

    def test_candidate_without_usable_text_prunes_nothing(self) -> None:
        for extra in ({99: Counter({"the": 20})}, {}):
            counts = {o: style(self.seeds[o]) for members in self.profiles.values() for o in members}
            counts.update(extra)
            index = TextStyleIndex(counts, {o: o for o in [*counts, 99]})
            decision = decide(index.rank(99, self.profiles), 1)
            self.assertFalse(decision.query_has_text)
            self.assertEqual(frozenset(), decision.pruned_profile_ids)
            self.assertEqual(set(self.profiles), set(decision.kept_profile_ids))

    def test_same_video_members_are_left_out(self) -> None:
        profiles = {**self.profiles, 7: [71]}
        videos = {o: o for o in [*self.seeds, 71]}
        videos[71] = videos[99]  # profile 7's only member is the candidate's own video
        index = index_for(profiles, {**self.seeds, 71: 3}, extra={99: style(3)}, videos=videos)
        ranking = index.rank(99, profiles)
        self.assertIn(7, ranking.pass_through_profile_ids)
        self.assertNotIn(7, [p for p, _ in ranking.ranked])

    def test_audit_payload_records_version_and_pruned_profiles(self) -> None:
        decision = decide(self.index().rank(99, self.profiles), 2)
        payload = decision.payload()
        self.assertEqual(TEXT_PREFILTER_VERSION, payload["scorer"]["version"])
        self.assertEqual(sorted(decision.pruned_profile_ids), payload["pruned_profile_ids"])
        self.assertTrue(payload["applied"])
        self.assertTrue(payload["text_never_decides_identity"])
        self.assertEqual(4, len(payload["text_ranked_profile_ids"]))


def _profile(profile_id: int, video_id: int):
    observation = SimpleNamespace(id=1000 + profile_id, video_id=video_id, input_fingerprint=f"o{profile_id}")
    readiness = ProfileAssociationReadiness(
        profile_id=profile_id, member_observation_ids=(observation.id,),
        member_fingerprints=(observation.input_fingerprint,), recording_count=3, source_count=1,
        normalized_names=(), shadow_ready=True, automatic_profile_ready=True, shadow_blockers=(),
        automatic_blockers=(), review_ready=True,
    )
    return readiness, (ShadowExemplar(profile_id, observation, Path(f"{profile_id}.wav"), f"a{profile_id}"),)


class RoutingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = tuple(_profile(k, k) for k in range(1, 5))
        self.sources = {k: k for k in range(1, 5)}
        # Acoustically, profile 2 is closest, then 3, then 4, then 1.
        self.centroids = {1001: (-1.0, 0.0), 1002: (0.9, 0.1), 1003: (0.8, 0.2), 1004: (0.7, 0.3)}

    def route(self, source_id: int = 99, **kwargs):
        return select_staged_association_profiles(
            self.profiles, candidate_source_id=source_id, candidate_normalized_names=(),
            source_id_by_video_id=self.sources, candidate_centroid=(1.0, 0.0),
            exemplar_centroids=self.centroids, maximum_global_profiles=1, **kwargs,
        )

    def test_off_by_default_is_identical(self) -> None:
        default = self.route()
        explicit_off = self.route(text_pruned_profile_ids=None)
        self.assertEqual(default, explicit_off)
        self.assertEqual((2,), default.shortlisted_profile_ids)
        for entry in default.candidate_funnel["retrieval_candidates"]:
            self.assertNotIn("text_prefilter_pruned", entry)

    def test_pruning_applies_to_cross_source_pool_only(self) -> None:
        pruned = self.route(text_pruned_profile_ids=frozenset({2, 4}))
        self.assertEqual((3,), pruned.shortlisted_profile_ids)
        entries = {e["profile_id"]: e for e in pruned.candidate_funnel["retrieval_candidates"]}
        self.assertTrue(entries[2]["text_prefilter_pruned"])
        self.assertIn("text_prefilter_pruned", entries[2]["routing_policy_exclusion_reason_codes"])
        self.assertFalse(entries[3]["text_prefilter_pruned"])
        # A source-local route is never pruned by text.
        local = self.route(source_id=2, text_pruned_profile_ids=frozenset({2}))
        self.assertEqual((2,), local.priority_profile_ids)
        self.assertIn(2, local.candidate_funnel["profiles_selected_for_comparison"])

    def test_route_plan_records_audit_only_when_enabled(self) -> None:
        database = SimpleNamespace(
            list_effective_profile_ids_for_observation=lambda _id: (),
            resolve_speaker_profile_id=lambda profile_id: profile_id,
        )
        common = dict(
            video=SimpleNamespace(id=50, source_id=99, title="Sermon"),
            observation=SimpleNamespace(id=500), readiness=tuple(p for p, _ in self.profiles),
            usable_profiles=self.profiles, eligible_exemplars=(), videos_by_id={},
            observations_by_id={}, source_id_by_video_id=self.sources,
            candidate_names_by_observation={}, minimum_profile_members=3, maximum_exemplars=3,
            minimum_same_exemplars=1, maximum_global_profiles=1, candidate_centroid=(1.0, 0.0),
            exemplar_centroids=self.centroids,
        )
        plain = plan_association_profile_route(database, **common)
        self.assertNotIn("text_prefilter", plain.routing_payload)
        decision = SimpleNamespace(pruned_profile_ids=frozenset({2}),
                                   payload=lambda: {"scorer": {"version": TEXT_PREFILTER_VERSION},
                                                    "pruned_profile_ids": [2]})
        filtered = plan_association_profile_route(database, text_prefilter=decision, **common)
        self.assertEqual([2], filtered.routing_payload["text_prefilter"]["pruned_profile_ids"])
        self.assertEqual((3,), filtered.routing.shortlisted_profile_ids)

    def test_preparation_scope_skips_profiles_pruned_for_every_video(self) -> None:
        readiness = tuple(p for p, _ in self.profiles)
        observations = {50: SimpleNamespace(id=500, video_id=50), 51: SimpleNamespace(id=501, video_id=51)}

        def scope(videos, decisions):
            return plan_association_preparation_scope(
                readiness, videos, observations_by_video_id=observations,
                observations_by_id={o.id: o for o in observations.values()},
                candidate_names_by_observation={}, source_id_by_video_id=self.sources,
                text_prefilter_by_observation=decisions,
            )

        one = (SimpleNamespace(id=50, source_id=99, title="Sermon"),)
        both = (*one, SimpleNamespace(id=51, source_id=98, title="Sermon"))
        prune = {500: SimpleNamespace(pruned_profile_ids=frozenset({1, 2})),
                 501: SimpleNamespace(pruned_profile_ids=frozenset({2, 3}))}
        self.assertEqual({1, 2, 3, 4}, {p.profile_id for p in scope(one, None).initial_profiles})
        self.assertEqual({3, 4}, {p.profile_id for p in scope(one, prune).initial_profiles})
        self.assertEqual({1, 3, 4}, {p.profile_id for p in scope(both, prune).initial_profiles})
        # A video without a decision (e.g. no text) prunes nothing for the batch.
        self.assertEqual({1, 2, 3, 4}, {p.profile_id for p in scope(both, {500: prune[500]}).initial_profiles})

    def test_request_default_is_off(self) -> None:
        request = ShadowAssociationRequest(
            youtube_video_id="v", all_eligible=False, unattempted_only=False, neighborhood_profile_ids=(),
            include_profiled=False, limit=None, plan_only=True, minimum_profile_members=3,
            maximum_exemplars=3, minimum_same_exemplars=2, maximum_global_profiles=1, jobs=1,
            model_path=Path("m"), model_sha256="x", policy_path=Path("p"), evaluation_root=Path("e"),
            cache_dir=Path("c"), output_root=Path("o"), base_dir=None,
        )
        self.assertIsNone(request.text_prefilter_top)


if __name__ == "__main__":
    unittest.main()
