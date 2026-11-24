"""Free per-sermon dimensions (spec section 4, step 2), computed in memory on caption-normalized text.

Scripture detection reuses the production detector (`detect_scripture_in_segments`) on the normalized
caption units, so rolling-caption repeats do not inflate counts; nothing is written to the database.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..caption_normalization import normalize_caption_fragments, should_normalize_rolling_captions
from ..pastor_fit.cleaning import tokens
from ..sermon_analysis import OLD_TESTAMENT_BOOKS, SermonSegment, _load_sermon_source, detect_scripture_in_segments
from ..structure_analysis import _mattr, _tokens as structure_tokens

FIRST_SINGULAR = {'i', 'me', 'my', 'mine', 'myself', "i'm", "i've", "i'll", "i'd"}
FIRST_PLURAL = {'we', 'us', 'our', 'ours', 'ourselves', "we're", "we've", "we'll", "we'd"}
SECOND_PERSON = {'you', 'your', 'yours', 'yourself', 'yourselves', "you're", "you've", "you'll", "you'd"}

# name -> (reader label, unit)
DIMENSIONS = {
    'F:scripture_references_per_1000_words': ('Scripture references per 1,000 words', 'per 1,000 words'),
    'F:scripture_text_engagement': ('Share of words that are recognized Bible text', 'share of words'),
    'F:old_testament_reference_share': ('Old Testament share of Scripture references', 'share of references'),
    'F:first_person_singular_per_1000': ('"I / me / my" per 1,000 words', 'per 1,000 words'),
    'F:first_person_plural_per_1000': ('"we / us / our" per 1,000 words', 'per 1,000 words'),
    'F:second_person_per_1000': ('"you / your" per 1,000 words', 'per 1,000 words'),
    'F:lexical_diversity_mattr': ('Vocabulary variety (moving type-token ratio)', 'ratio'),
    'F:sermon_minutes': ('Sermon length', 'minutes'),
}


def normalized_segments(path: Path) -> tuple[list[SermonSegment], float]:
    payload = json.loads(Path(path).read_text())
    segments, _, duration = _load_sermon_source(Path(path))
    if not should_normalize_rolling_captions(payload):
        return segments, duration
    by_index = {s.index: s for s in segments}
    normalized = normalize_caption_fragments((s.index, s.text) for s in segments)
    units = []
    for unit in normalized.units:
        sources = [by_index[i] for i in unit.source_segment_indexes if i in by_index]
        if not sources or not unit.text.strip():
            continue
        units.append(SermonSegment(index=sources[0].index, start_seconds=sources[0].start_seconds,
                                   end_seconds=sources[-1].end_seconds, text=unit.text))
    return units, duration


def _per_thousand(count: int, words: int) -> float | None:
    return 1000 * count / words if words else None


def measure(path: Path) -> dict[str, float | None]:
    segments, duration = normalized_segments(path)
    text = '\n'.join(s.text for s in segments)
    words = tokens(text)
    references, alignments = detect_scripture_in_segments(segments)
    aligned_words = sum(int(item['transcript_span_word_count']) for item in alignments)
    old = sum(1 for item in references if item['book'] in OLD_TESTAMENT_BOOKS)
    return {
        'F:scripture_references_per_1000_words': _per_thousand(len(references), len(words)),
        'F:scripture_text_engagement': aligned_words / len(words) if words else None,
        'F:old_testament_reference_share': old / len(references) if references else None,
        'F:first_person_singular_per_1000': _per_thousand(sum(w in FIRST_SINGULAR for w in words), len(words)),
        'F:first_person_plural_per_1000': _per_thousand(sum(w in FIRST_PLURAL for w in words), len(words)),
        'F:second_person_per_1000': _per_thousand(sum(w in SECOND_PERSON for w in words), len(words)),
        'F:lexical_diversity_mattr': _mattr(structure_tokens(text)),
        'F:sermon_minutes': duration / 60 if duration else None,
        'words': len(words),
    }
