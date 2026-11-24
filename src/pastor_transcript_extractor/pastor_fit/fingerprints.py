"""Fingerprints (spec section 4, steps 5a and 5b) and their saved form.

5a stylometry: word counts per sermon, kept for the corpus's 2,000 most frequent words of each
text variant (Burrows' Delta later uses the top 300 of them).
5b embeddings: about 150-word chunks of each sermon, embedded with the locked local MiniLM
encoder; vectors are cached by chunk text hash so a rerun never re-encodes.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping

import numpy as np

from .cleaning import tokens

KEPT_WORDS = 2000
CHUNK_WORDS = 150
MIN_CHUNK_WORDS = 10


def word_counts(texts: Mapping[int, str]) -> dict:
    counts = {video_id: Counter(tokens(text)) for video_id, text in texts.items()}
    corpus: Counter = Counter()
    for value in counts.values():
        corpus.update(value)
    vocabulary = [word for word, _ in sorted(corpus.items(), key=lambda item: (-item[1], item[0]))[:KEPT_WORDS]]
    kept = set(vocabulary)
    return {'vocabulary': vocabulary,
            'sermons': {str(v): {'total': sum(c.values()), 'counts': {w: n for w, n in c.items() if w in kept}}
                        for v, c in counts.items()}}


def chunks(text: str) -> list[str]:
    words = text.split()
    return [' '.join(words[i:i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)
            if len(words[i:i + CHUNK_WORDS]) >= MIN_CHUNK_WORDS]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class EmbeddingCache:
    def __init__(self, path: Path):
        self.path = path
        self.vectors: dict[str, np.ndarray] = {}
        if path.exists():
            data = np.load(path, allow_pickle=False)
            for key, vector in zip(data['keys'], data['vectors']):
                self.vectors[str(key)] = vector

    def save(self) -> None:
        keys = sorted(self.vectors)
        matrix = np.stack([self.vectors[k] for k in keys]) if keys else np.zeros((0, 384), dtype=np.float32)
        temporary = self.path.with_suffix('.tmp.npz')
        np.savez(temporary, keys=np.array(keys), vectors=matrix.astype(np.float32))
        temporary.replace(self.path)


def embed_chunks(text: str, encode: Callable[[str], list[float] | None], cache: EmbeddingCache,
                 stats: Counter) -> list[tuple[str, str]]:
    """Return (chunk text, cache key) pairs; chunks too long for the model are halved until they fit."""
    result = []
    pending = chunks(text)
    while pending:
        piece = pending.pop(0)
        key = _sha(piece)
        if key not in cache.vectors:
            vector = encode(piece)
            if vector is None:
                words = piece.split()
                if len(words) < 2 * MIN_CHUNK_WORDS:
                    stats['dropped_chunks'] += 1
                    continue
                half = len(words) // 2
                pending[:0] = [' '.join(words[:half]), ' '.join(words[half:])]
                stats['split_chunks'] += 1
                continue
            cache.vectors[key] = np.asarray(vector, dtype=np.float32)
            stats['encoded'] += 1
        else:
            stats['cached'] += 1
        result.append((piece, key))
    return result


def build_embeddings(texts: Mapping[int, str], encode, cache: EmbeddingCache, progress=None) -> tuple[dict, Counter]:
    stats: Counter = Counter()
    out = {}
    for number, (video_id, text) in enumerate(sorted(texts.items()), 1):
        out[str(video_id)] = [{'key': key, 'text': piece} for piece, key in embed_chunks(text, encode, cache, stats)]
        if progress and number % 10 == 0:
            progress(number, len(texts), stats)
            cache.save()
    cache.save()
    return out, stats


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True))
    temporary.replace(path)
