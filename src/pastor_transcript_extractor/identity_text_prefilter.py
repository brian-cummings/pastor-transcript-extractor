"""Opt-in stylometric pre-filter for speaker identity retrieval.

Text never decides identity. For one candidate observation it ranks speaker profiles by
Burrows' Delta over sermon-window text (the pastor fit experiment's "how they talk"
fingerprint, docs/PASTOR_FIT_EXPERIMENT.md sections 4, 11, 12 and 13) and keeps the top N for
voice work. Two rules keep it from acting as evidence against a match:

- a candidate without usable text prunes nothing;
- a profile without usable text is never pruned; it always goes through to voice.

Every decision carries the scorer version and the pruned profile ids, so association reports
show which profiles text removed and can be replayed without it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .pastor_fit.cleaning import tokens
from .pastor_fit.corpus import window_text
from .pastor_fit.experiment import STYLE_WORDS, Fingerprints, distances
from .pastor_fit.fingerprints import KEPT_WORDS, counts_from_counters

TEXT_PREFILTER_VERSION = "identity_text_prefilter_v1"
DEFAULT_TOP = 5
# Fixed before any registry-scale result: below this many words a sermon-window text (or a
# profile's pooled text) is treated as absent, so it can never cause pruning.
MINIMUM_USABLE_WORDS = 500
SCORER = {
    "version": TEXT_PREFILTER_VERSION,
    "method": "burrows_delta",
    "style_words": STYLE_WORDS,
    "kept_words": KEPT_WORDS,
    "text": "extraction_sermon_window_rolling_caption_normalized",
    "minimum_usable_words": MINIMUM_USABLE_WORDS,
}
_COUNT_CACHE_VERSION = "identity_text_prefilter_counts_v1"


def observation_word_counts(path: Path, cache_root: Path | None = None) -> Counter | None:
    """Token counts of one extraction's sermon window, or None when it has no usable window.

    The cache is keyed by path, size and modification time; it is a speed-up only.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    key = hashlib.sha256(json.dumps(
        [_COUNT_CACHE_VERSION, str(path.resolve()), stat.st_size, stat.st_mtime_ns]
    ).encode()).hexdigest()
    cached = cache_root / f"{key}.json" if cache_root is not None else None
    if cached is not None:
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
            if payload.get("version") == _COUNT_CACHE_VERSION:
                return None if payload["counts"] is None else Counter(payload["counts"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    try:
        text, _info = window_text(path)
        counts: Counter | None = Counter(tokens(text))
    except (OSError, ValueError, KeyError, TypeError):
        counts = None
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(
            {"version": _COUNT_CACHE_VERSION, "path": str(path), "counts": counts}
        ), encoding="utf-8")
        temporary.replace(cached)
    return counts


@dataclass(frozen=True, slots=True)
class TextRanking:
    """One candidate's profiles ordered by stylometric distance (closest first)."""

    observation_id: int
    query_has_text: bool
    ranked: tuple[tuple[int, float], ...]
    # Profiles text did not rank: no usable text of their own, or no ranking was possible
    # (candidate without usable text, or fewer than two profiles with text). Never pruned.
    pass_through_profile_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TextPrefilterDecision:
    observation_id: int
    top: int
    query_has_text: bool
    kept_profile_ids: tuple[int, ...]
    pruned_profile_ids: frozenset[int]
    pass_through_profile_ids: tuple[int, ...]
    ranked: tuple[tuple[int, float], ...]

    def payload(self) -> dict[str, Any]:
        """Audit record stored in the association routing (and so in its fingerprint)."""
        return {
            "scorer": dict(SCORER),
            "top": self.top,
            "observation_id": self.observation_id,
            "query_has_usable_text": self.query_has_text,
            "applied": bool(self.pruned_profile_ids),
            "text_never_decides_identity": True,
            "text_ranked_profile_ids": [profile_id for profile_id, _ in self.ranked],
            "text_distances": {str(p): round(d, 6) for p, d in self.ranked},
            "kept_profile_ids": list(self.kept_profile_ids),
            "pruned_profile_ids": sorted(self.pruned_profile_ids),
            "pass_through_profile_ids": list(self.pass_through_profile_ids),
        }


class TextStyleIndex:
    """Delta fingerprints for a set of observations (keyed by observation id)."""

    def __init__(self, counts_by_observation: Mapping[int, Counter | None],
                 video_by_observation: Mapping[int, int]):
        present = {o: c for o, c in counts_by_observation.items() if c}
        self.fingerprints = Fingerprints(counts_from_counters(present), {}, {})
        self.video_by_observation = dict(video_by_observation)

    def words(self, observation_ids: Iterable[int]) -> int:
        return sum(self.fingerprints.style_totals.get(o, 0) for o in observation_ids)

    def rank(self, observation_id: int, profile_members: Mapping[int, Sequence[int]]) -> TextRanking:
        """Rank profiles for one observation. Members recorded in the same video as the
        observation are left out of every profile (leave-one-out), so its own text never
        matches itself."""
        own_video = self.video_by_observation.get(observation_id)
        query_ids = [observation_id] if observation_id in self.fingerprints.style_totals else []
        query_has_text = self.words(query_ids) >= MINIMUM_USABLE_WORDS
        with_text: list[tuple[int, Any]] = []
        no_text: list[int] = []
        for profile_id in sorted(profile_members):
            members = [o for o in dict.fromkeys(profile_members[profile_id])
                       if o in self.fingerprints.style_totals
                       and o != observation_id
                       and self.video_by_observation.get(o) != own_video]
            if self.words(members) >= MINIMUM_USABLE_WORDS:
                with_text.append((profile_id, self.fingerprints.style(members)))
            else:
                no_text.append(profile_id)
        if not query_has_text or len(with_text) < 2:
            return TextRanking(observation_id, query_has_text, (),
                               tuple(sorted(no_text + [p for p, _ in with_text])))
        vectors = [vector for _, vector in with_text]
        query = self.fingerprints.style(query_ids)
        scored = sorted(zip((p for p, _ in with_text), distances("style", query, vectors, vectors)),
                        key=lambda item: (item[1], item[0]))
        return TextRanking(observation_id, True, tuple(scored), tuple(no_text))


def decide(ranking: TextRanking, top: int) -> TextPrefilterDecision:
    """Keep the `top` closest ranked profiles and every profile text did not rank."""
    if top < 1:
        raise ValueError("text pre-filter top must be at least 1")
    kept = [profile_id for profile_id, _ in ranking.ranked[:top]]
    pruned = frozenset(profile_id for profile_id, _ in ranking.ranked[top:])
    return TextPrefilterDecision(
        observation_id=ranking.observation_id,
        top=top,
        query_has_text=ranking.query_has_text,
        kept_profile_ids=tuple(kept) + ranking.pass_through_profile_ids,
        pruned_profile_ids=pruned,
        pass_through_profile_ids=ranking.pass_through_profile_ids,
        ranked=ranking.ranked,
    )


def extraction_paths_by_observation(database) -> tuple[dict[int, Path], dict[int, int]]:
    """Each observation's extraction JSON (its sermon window is the observation span) and video."""
    extraction_paths = {e.id: e.proposed_json_path for e in database.list_extraction_results()}
    paths: dict[int, Path] = {}
    videos: dict[int, int] = {}
    for observation in database.list_speaker_observations():
        videos[observation.id] = observation.video_id
        path = extraction_paths.get(observation.extraction_result_id)
        if path:
            paths[observation.id] = Path(path)
    return paths, videos


def load_index(paths: Mapping[int, Path], videos: Mapping[int, int],
               observation_ids: Iterable[int], cache_root: Path | None) -> TextStyleIndex:
    counts_by_path: dict[Path, Counter | None] = {}
    counts: dict[int, Counter | None] = {}
    for observation_id in sorted(set(observation_ids)):
        path = paths.get(observation_id)
        if path is None:
            continue
        if path not in counts_by_path:
            counts_by_path[path] = observation_word_counts(path, cache_root)
        counts[observation_id] = counts_by_path[path]
    return TextStyleIndex(counts, videos)


def plan_text_prefilter(database, profile_members: Mapping[int, Sequence[int]],
                        candidate_observation_ids: Iterable[int], *, top: int,
                        cache_root: Path | None) -> dict[int, TextPrefilterDecision]:
    """Decisions for the requested candidates against the given profiles (no voice work)."""
    candidates = sorted(set(candidate_observation_ids))
    paths, videos = extraction_paths_by_observation(database)
    member_ids = [o for members in profile_members.values() for o in members]
    index = load_index(paths, videos, [*member_ids, *candidates], cache_root)
    return {o: decide(index.rank(o, profile_members), top) for o in candidates}
