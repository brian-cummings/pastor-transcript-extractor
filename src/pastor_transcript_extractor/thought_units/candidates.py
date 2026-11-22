"""Deterministic candidate boundaries over the saved (already rolling-caption-normalized) sermon text. No text is edited."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from pastor_transcript_extractor.sermon_topics import _SENTENCE_END

MIN_SIDE_WORDS = 4
LONG_PIECE_WORDS = 60   # longer stretches without terminal punctuation become caption-line candidates
WINDOW = 3              # sentences on each side of a candidate
LOOK_AHEAD = 8          # sentences an aside may span (spec section 4)
_WORD = re.compile(r"[\w']+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


@dataclass(frozen=True)
class Piece:
    start: int
    end: int


def split_pieces(text: str) -> list[Piece]:
    """Sentence pieces by the project's sentence-end pattern; a piece that repeats the previous piece's tail joins it."""
    raw, cursor = [], 0
    for match in _SENTENCE_END.finditer(text):
        chunk = text[cursor:match.end()]
        start, end = cursor + len(chunk) - len(chunk.lstrip()), cursor + len(chunk.rstrip())
        if start < end:
            raw.append(Piece(start, end))
        cursor = match.end()
    rest = text[cursor:]
    if rest.strip():
        raw.append(Piece(cursor + len(rest) - len(rest.lstrip()), cursor + len(rest.rstrip())))
    merged: list[Piece] = []
    for piece in raw:
        current = words(text[piece.start:piece.end])
        previous = words(text[merged[-1].start:merged[-1].end]) if merged else []
        if merged and 0 < len(current) <= 8 and len(previous) >= len(current) and previous[-len(current):] == current:
            merged[-1] = Piece(merged[-1].start, piece.end)
        else:
            merged.append(piece)
    result: list[Piece] = []
    for piece in merged:  # long stretches without terminal punctuation: caption-line ends become candidates
        body = text[piece.start:piece.end]
        if len(words(body)) <= LONG_PIECE_WORDS or '\n' not in body:
            result.append(piece)
            continue
        cursor = piece.start
        for line in body.split('\n'):
            line_end = cursor + len(line)
            if line.strip():
                result.append(Piece(cursor + len(line) - len(line.lstrip()), cursor + len(line.rstrip())))
            cursor = line_end + 1
    return result


def collapse(text: str) -> str:
    return ' '.join(text.split())


@dataclass(frozen=True)
class Candidate:
    index: int      # the boundary after piece `index`
    position: int   # character offset of the end of that piece


def candidates(text: str, pieces: Sequence[Piece]) -> list[Candidate]:
    return [Candidate(i, pieces[i].end) for i in range(len(pieces) - 1)
            if len(words(text[pieces[i].start:pieces[i].end])) >= MIN_SIDE_WORDS
            and len(words(text[pieces[i + 1].start:pieces[i + 1].end])) >= MIN_SIDE_WORDS]


def span(text: str, pieces: Sequence[Piece], first: int, last: int) -> str:
    first, last = max(0, first), min(len(pieces) - 1, last)
    return collapse(text[pieces[first].start:pieces[last].end]) if first <= last else ''


def passages(text: str, pieces: Sequence[Piece], index: int, skip: int = 0) -> tuple[str, str, str]:
    """Before (WINDOW pieces ending at `index`), the skipped pieces (an aside, when skip > 0) and the after window."""
    before = span(text, pieces, index - WINDOW + 1, index)
    between = span(text, pieces, index + 1, index + skip) if skip else ''
    after = span(text, pieces, index + skip + 1, index + skip + WINDOW)
    return before, between, after
