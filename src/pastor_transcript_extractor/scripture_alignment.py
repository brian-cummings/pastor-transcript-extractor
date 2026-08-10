from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


ALIGNMENT_POLICY_VERSION = "conservative-token-alignment-v1"
_DATA_DIR = Path(__file__).with_name("data")
_SOURCE_PATH = _DATA_DIR / "engwebp-2020-stable.vpl.txt.gz"
_PROVENANCE_PATH = _DATA_DIR / "engwebp-2020-stable.provenance.json"
_RARE_TOKEN_MAX_VERSES = 180
_TOKEN_PATTERN = re.compile(r"\b[\w]+(?:['’][\w]+)?\b", re.UNICODE)
_VPL_PATTERN = re.compile(r"^(\S+) (\d+):(\d+) ?(.*)$")
_STOPWORDS = frozenset(
    "a an and are as at be been but by for from had has have he her him his i in "
    "is it its me my not of on or our she that the their them there they this to "
    "us was we were what when which who will with you your".split()
)
_BOOK_CODES = dict(
    zip(
        "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST "
        "JOB PSA PRO ECC SOL ISA JER LAM EZE DAN HOS JOE AMO OBA JON MIC NAH HAB "
        "ZEP HAG ZEC MAL MAT MAR LUK JOH ACT ROM 1CO 2CO GAL EPH PHI COL 1TH 2TH "
        "1TI 2TI TIT PHM HEB JAM 1PE 2PE 1JO 2JO 3JO JUD REV".split(),
        (
            "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua",
            "Judges", "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings",
            "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job",
            "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon", "Isaiah",
            "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
            "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai",
            "Zechariah", "Malachi", "Matthew", "Mark", "Luke", "John", "Acts",
            "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
            "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
            "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James",
            "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation",
        ),
        strict=True,
    )
)


@dataclass(frozen=True, slots=True)
class AlignmentSegment:
    index: int
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ReferenceAnchor:
    segment_index: int
    book: str
    chapter: int | None
    verse_start: int | None
    verse_end: int | None
    canonical_reference: str
    detection_class: str


@dataclass(frozen=True, slots=True)
class BibleVerse:
    book: str
    chapter: int
    verse: int
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BibleCorpus:
    verses: tuple[BibleVerse, ...]
    provenance: dict[str, object]
    token_document_frequency: Counter[str]
    rare_token_index: dict[str, tuple[int, ...]]
    reference_index: dict[tuple[str, int, int], int]
    chapter_index: dict[tuple[str, int], tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class _TranscriptToken:
    value: str
    segment_index: int
    char_start: int
    char_end: int


def _normalize_token(value: str) -> str:
    normalized = value.casefold().replace("’", "'")
    return normalized[:-2] if normalized.endswith("'s") else normalized


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_normalize_token(match.group()) for match in _TOKEN_PATTERN.finditer(text))


@lru_cache(maxsize=1)
def load_bible_corpus() -> BibleCorpus:
    provenance = json.loads(_PROVENANCE_PATH.read_text(encoding="utf-8"))
    raw = gzip.decompress(_SOURCE_PATH.read_bytes())
    content_sha = hashlib.sha256(raw).hexdigest()
    if content_sha != provenance["artifact_content_sha256"]:
        raise ValueError("Bundled Bible text does not match its provenance checksum")
    verses: list[BibleVerse] = []
    for line in raw.decode("utf-8").splitlines():
        match = _VPL_PATTERN.match(line)
        if match is None or match.group(1) not in _BOOK_CODES:
            raise ValueError(f"Invalid bundled Bible VPL line: {line[:80]}")
        text = match.group(4)
        verses.append(
            BibleVerse(
                book=_BOOK_CODES[match.group(1)],
                chapter=int(match.group(2)),
                verse=int(match.group(3)),
                text=text,
                tokens=_tokens(text),
            )
        )
    document_frequency: Counter[str] = Counter()
    for verse in verses:
        document_frequency.update(set(verse.tokens) - _STOPWORDS)
    rare_index: dict[str, list[int]] = defaultdict(list)
    reference_index: dict[tuple[str, int, int], int] = {}
    chapter_index: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, verse in enumerate(verses):
        reference_index[(verse.book, verse.chapter, verse.verse)] = index
        chapter_index[(verse.book, verse.chapter)].append(index)
        for token in set(verse.tokens) - _STOPWORDS:
            if document_frequency[token] <= _RARE_TOKEN_MAX_VERSES:
                rare_index[token].append(index)
    return BibleCorpus(
        verses=tuple(verses),
        provenance=provenance,
        token_document_frequency=document_frequency,
        rare_token_index={key: tuple(value) for key, value in rare_index.items()},
        reference_index=reference_index,
        chapter_index={key: tuple(value) for key, value in chapter_index.items()},
    )


def bible_source_provenance() -> dict[str, object]:
    return dict(load_bible_corpus().provenance)


def _transcript_tokens(segments: Iterable[AlignmentSegment]) -> list[_TranscriptToken]:
    result: list[_TranscriptToken] = []
    for segment in segments:
        for match in _TOKEN_PATTERN.finditer(segment.text):
            result.append(
                _TranscriptToken(
                    value=_normalize_token(match.group()),
                    segment_index=segment.index,
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
    return result


def _passage_indexes(corpus: BibleCorpus, center: int) -> Iterable[tuple[int, ...]]:
    verse = corpus.verses[center]
    chapter = corpus.chapter_index[(verse.book, verse.chapter)]
    position = chapter.index(center)
    for width in (1, 2, 3):
        for start in range(max(0, position - width + 1), min(position + 1, len(chapter) - width + 1)):
            yield chapter[start : start + width]


def _canonical_passage(verses: list[BibleVerse]) -> str:
    first, last = verses[0], verses[-1]
    if first.verse == last.verse:
        return f"{first.book} {first.chapter}:{first.verse}"
    return f"{first.book} {first.chapter}:{first.verse}-{last.verse}"


def _candidate_indexes(
    corpus: BibleCorpus,
    transcript_values: list[str],
    anchors: list[ReferenceAnchor],
) -> tuple[set[int], set[int]]:
    votes: Counter[int] = Counter()
    for token in set(transcript_values) - _STOPWORDS:
        for index in corpus.rare_token_index.get(token, ()):
            votes[index] += 1
    anchored: set[int] = set()
    for anchor in anchors:
        if anchor.chapter is None:
            continue
        chapter = corpus.chapter_index.get((anchor.book, anchor.chapter), ())
        if anchor.verse_start is None:
            anchored.update(
                index
                for index, count in sorted(
                    ((index, votes[index]) for index in chapter),
                    key=lambda item: (-item[1], item[0]),
                )[:24]
                if count > 0
            )
            continue
        end = anchor.verse_end or anchor.verse_start
        for verse_number in range(max(1, anchor.verse_start - 1), end + 3):
            index = corpus.reference_index.get((anchor.book, anchor.chapter, verse_number))
            if index is not None:
                anchored.add(index)
    independent = {index for index, count in votes.most_common(16) if count >= 2}
    return anchored, independent


def _score_passage(
    corpus: BibleCorpus,
    passage_indexes: tuple[int, ...],
    transcript_values: list[str],
    *,
    anchored: bool,
) -> dict[str, object] | None:
    passage = [corpus.verses[index] for index in passage_indexes]
    bible_values = [token for verse in passage for token in verse.tokens]
    if len(bible_values) < 7 or len(bible_values) > 105:
        return None
    matcher = SequenceMatcher(None, bible_values, transcript_values, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    matched = sum(block.size for block in blocks)
    longest = max((block.size for block in blocks), default=0)
    bible_coverage = matched / len(bible_values)
    transcript_span_start = min((block.b for block in blocks), default=0)
    transcript_span_end = max((block.b + block.size for block in blocks), default=0)
    span_words = transcript_span_end - transcript_span_start
    span_coverage = matched / span_words if span_words else 0.0
    rare_shared = {
        token
        for token in set(bible_values) & set(transcript_values)
        if token not in _STOPWORDS
        and corpus.token_document_frequency[token] <= _RARE_TOKEN_MAX_VERSES
    }
    score = 0.7 * bible_coverage + 0.3 * span_coverage
    accepted = (
        matched >= 6
        and bible_coverage >= 0.38
        and (longest >= 3 or len(rare_shared) >= 2)
        if anchored
        else matched >= 9
        and bible_coverage >= 0.58
        and longest >= 4
        and len(rare_shared) >= 2
        and span_coverage >= 0.48
    )
    if not accepted:
        return None
    return {
        "passage_indexes": passage_indexes,
        "canonical_reference": _canonical_passage(passage),
        "book": passage[0].book,
        "chapter": passage[0].chapter,
        "verse_start": passage[0].verse,
        "verse_end": passage[-1].verse,
        "bible_text": " ".join(verse.text for verse in passage),
        "alignment_score": round(score, 6),
        "bible_token_coverage": round(bible_coverage, 6),
        "transcript_span_token_coverage": round(span_coverage, 6),
        "matched_token_count": matched,
        "longest_exact_run_tokens": longest,
        "rare_shared_tokens": sorted(rare_shared),
        "transcript_token_start": transcript_span_start,
        "transcript_token_end": transcript_span_end,
    }


def _chunks(segments: list[AlignmentSegment]) -> Iterable[list[AlignmentSegment]]:
    for start in range(len(segments)):
        chunk: list[AlignmentSegment] = []
        words = 0
        for segment in segments[start : start + 8]:
            chunk.append(segment)
            words += len(_tokens(segment.text))
            if words >= 52:
                break
        if words >= 10:
            yield chunk


def detect_scripture_alignments(
    segments: list[AlignmentSegment],
    anchors: list[ReferenceAnchor] | None = None,
) -> list[dict[str, object]]:
    corpus = load_bible_corpus()
    anchors = anchors or []
    candidates: list[dict[str, object]] = []
    segment_by_index = {segment.index: segment for segment in segments}
    for chunk in _chunks(segments):
        transcript = _transcript_tokens(chunk)
        values = [token.value for token in transcript]
        chunk_start, chunk_end = chunk[0].index, chunk[-1].index
        nearby_anchors = [
            anchor
            for anchor in anchors
            if chunk_start - 1 <= anchor.segment_index <= chunk_end
        ]
        anchored_indexes, independent_indexes = _candidate_indexes(
            corpus, values, nearby_anchors
        )
        seen_passages: set[tuple[int, ...]] = set()
        for center in anchored_indexes | independent_indexes:
            is_anchored = center in anchored_indexes
            for passage_indexes in _passage_indexes(corpus, center):
                if passage_indexes in seen_passages:
                    continue
                seen_passages.add(passage_indexes)
                result = _score_passage(
                    corpus, passage_indexes, values, anchored=is_anchored
                )
                if result is None:
                    continue
                start_token = transcript[int(result.pop("transcript_token_start"))]
                end_token = transcript[int(result.pop("transcript_token_end")) - 1]
                first_segment = segment_by_index[start_token.segment_index]
                last_segment = segment_by_index[end_token.segment_index]
                if first_segment.index == last_segment.index:
                    excerpt = first_segment.text[start_token.char_start : end_token.char_end]
                    char_start: int | None = start_token.char_start
                    char_end: int | None = end_token.char_end
                else:
                    covered_segments = [
                        segment
                        for segment in segments
                        if first_segment.index <= segment.index <= last_segment.index
                    ]
                    covered = [
                        (
                            segment.text[start_token.char_start :]
                            if segment.index == first_segment.index
                            else segment.text[: end_token.char_end]
                            if segment.index == last_segment.index
                            else segment.text
                        )
                        for segment in covered_segments
                    ]
                    excerpt = " ".join(covered)
                    char_start = None
                    char_end = None
                matching_anchor = next(
                    (
                        anchor
                        for anchor in nearby_anchors
                        if anchor.book == result["book"]
                        and anchor.chapter == result["chapter"]
                    ),
                    None,
                )
                result.update(
                    {
                        "alignment_class": "anchored" if is_anchored else "independent",
                        "alignment_method": ALIGNMENT_POLICY_VERSION,
                        "anchor_canonical_reference": (
                            matching_anchor.canonical_reference if matching_anchor else None
                        ),
                        "anchor_detection_class": (
                            matching_anchor.detection_class if matching_anchor else None
                        ),
                        "source_segment_start_index": first_segment.index,
                        "source_segment_end_index": last_segment.index,
                        "start_seconds": first_segment.start_seconds,
                        "end_seconds": last_segment.end_seconds,
                        "char_start": char_start,
                        "char_end": char_end,
                        "excerpt": excerpt,
                        "transcript_span_word_count": len(_tokens(excerpt)),
                    }
                )
                candidates.append(result)

    selected: list[dict[str, object]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            -float(item["alignment_score"]),
            -int(item["matched_token_count"]),
            str(item["canonical_reference"]),
        ),
    ):
        overlaps = any(
            int(candidate["source_segment_start_index"])
            <= int(existing["source_segment_end_index"])
            and int(existing["source_segment_start_index"])
            <= int(candidate["source_segment_end_index"])
            for existing in selected
        )
        if not overlaps:
            selected.append(candidate)
    return sorted(
        selected,
        key=lambda item: (
            int(item["source_segment_start_index"]),
            str(item["canonical_reference"]),
        ),
    )
