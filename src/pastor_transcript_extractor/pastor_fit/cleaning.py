"""Channel boilerplate and channel vocabulary removal (spec section 4, steps 2, 3 and 6).

Every sermon yields three texts:
- `clean`: boilerplate units removed (step 2);
- `stripped`: clean text with channel-vocabulary words also removed (step 3);
- `baseline`: only what steps 2 and 3 removed (step 6, the channel-only baseline).
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import re
from typing import Iterable, Mapping

SHINGLE = 8
BOILERPLATE_SHARE = 0.30
BOILERPLATE_MIN_SERMONS = 3
UNIT_MAX_WORDS = 40
VOCAB_CHANNEL_SHARE = 0.50
VOCAB_OTHER_SHARE = 0.05
VOCAB_MIN_SERMONS = 3

_SENTENCE_END = re.compile(r'(?<=[.?!])\s+|\n+')
_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def units(text: str) -> list[str]:
    """Sentences, or 40-word pieces where captions have no punctuation."""
    pieces = []
    for sentence in _SENTENCE_END.split(text):
        words = sentence.split()
        for start in range(0, len(words), UNIT_MAX_WORDS):
            if words[start:start + UNIT_MAX_WORDS]:
                pieces.append(' '.join(words[start:start + UNIT_MAX_WORDS]))
    return pieces


def shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def boilerplate_shingles(texts: Mapping[int, str], channel_of: Mapping[int, int]) -> dict[int, set]:
    """Per channel: 8-word sequences found in at least 30% (and at least 3) of its sermons.

    Sequences are counted over the whole sermon text, so one spanning a unit boundary still counts.
    """
    by_channel: dict[int, Counter] = defaultdict(Counter)
    sizes: Counter = Counter()
    for video_id, text in texts.items():
        channel = channel_of[video_id]
        sizes[channel] += 1
        by_channel[channel].update(shingles(tokens(text)))
    result = {}
    for channel, counts in by_channel.items():
        floor = max(BOILERPLATE_MIN_SERMONS, math.ceil(BOILERPLATE_SHARE * sizes[channel]))
        result[channel] = {gram for gram, n in counts.items() if n >= floor}
    return result


def split_boilerplate(text: str, grams: set) -> tuple[list[str], list[str]]:
    """Return (kept units, boilerplate units). A unit is boilerplate if any word of it lies in a
    boilerplate sequence of the whole text (so short units inside a repeated passage go too)."""
    pieces = units(text)
    owner: list[int] = []
    words: list[str] = []
    for index, unit in enumerate(pieces):
        unit_words = tokens(unit)
        words.extend(unit_words)
        owner.extend([index] * len(unit_words))
    marked: set[int] = set()
    if grams:
        for start in range(len(words) - SHINGLE + 1):
            if tuple(words[start:start + SHINGLE]) in grams:
                marked.update(owner[start:start + SHINGLE])
    kept = [unit for index, unit in enumerate(pieces) if index not in marked]
    removed = [unit for index, unit in enumerate(pieces) if index in marked]
    return kept, removed


def channel_vocabulary(token_sets: Mapping[int, set], channel_of: Mapping[int, int]) -> dict[int, set]:
    """Per channel (3+ sermons): words in at least half its sermons and under 5% of other channels' sermons."""
    sermons_by_channel: dict[int, list[int]] = defaultdict(list)
    for video_id in token_sets:
        sermons_by_channel[channel_of[video_id]].append(video_id)
    document_frequency: Counter = Counter()
    for words in token_sets.values():
        document_frequency.update(words)
    total = len(token_sets)
    result = {}
    for channel, members in sermons_by_channel.items():
        if len(members) < VOCAB_MIN_SERMONS:
            result[channel] = set()
            continue
        inside: Counter = Counter()
        for video_id in members:
            inside.update(token_sets[video_id])
        others = total - len(members)
        vocabulary = set()
        for word, n in inside.items():
            outside = document_frequency[word] - n
            if n / len(members) >= VOCAB_CHANNEL_SHARE and (others == 0 or outside / others < VOCAB_OTHER_SHARE):
                vocabulary.add(word)
        result[channel] = vocabulary
    return result


def remove_words(text: str, vocabulary: set) -> tuple[str, list[str]]:
    """Drop whitespace-separated words whose normalized tokens are all in the vocabulary."""
    kept, removed = [], []
    for word in text.split():
        normalized = tokens(word)
        (removed if normalized and all(t in vocabulary for t in normalized) else kept).append(word)
    return ' '.join(kept), removed


def variants(texts: Mapping[int, str], channel_of: Mapping[int, int]) -> tuple[dict[str, dict[int, str]], dict]:
    """Build the clean, stripped and baseline text of every sermon, and the removal record."""
    grams = boilerplate_shingles(texts, channel_of)
    clean, boiler = {}, {}
    for video_id, text in texts.items():
        kept, removed = split_boilerplate(text, grams[channel_of[video_id]])
        clean[video_id] = '\n'.join(kept)
        boiler[video_id] = removed
    vocabulary = channel_vocabulary({v: set(tokens(t)) for v, t in clean.items()}, channel_of)
    stripped, baseline = {}, {}
    record: dict = {'channels': {}, 'sermons': {}}
    for video_id, text in clean.items():
        kept_text, removed_words = remove_words(text, vocabulary[channel_of[video_id]])
        stripped[video_id] = kept_text
        baseline[video_id] = '\n'.join(boiler[video_id] + ([' '.join(removed_words)] if removed_words else []))
        record['sermons'][str(video_id)] = {
            'words': len(texts[video_id].split()), 'boilerplate_units': len(boiler[video_id]),
            'boilerplate_words': sum(len(u.split()) for u in boiler[video_id]),
            'channel_vocabulary_words_removed': len(removed_words)}
    for channel in sorted(set(channel_of.values())):
        record['channels'][str(channel)] = {
            'boilerplate_sequences': len(grams.get(channel, ())),
            'channel_vocabulary': sorted(vocabulary.get(channel, ()))}
    return {'clean': clean, 'stripped': stripped, 'baseline': baseline}, record


def nonempty(values: Iterable[str]) -> int:
    return sum(1 for value in values if value.strip())
