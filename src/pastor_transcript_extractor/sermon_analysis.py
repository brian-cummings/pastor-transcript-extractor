from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from pastor_transcript_extractor.models import SermonAnalysisRun, Video
from pastor_transcript_extractor.storage import Database


ANALYZER_KEY = "sermon-basics"
ANALYZER_VERSION = "2"
ANALYSIS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    run: SermonAnalysisRun
    created: bool


@dataclass(frozen=True, slots=True)
class _SermonSegment:
    index: int
    start_seconds: float | None
    end_seconds: float | None
    text: str


_BOOK_ALIASES: dict[str, tuple[str, ...]] = {
    "Genesis": ("Genesis", "Gen"),
    "Exodus": ("Exodus", "Exod", "Ex"),
    "Leviticus": ("Leviticus", "Lev"),
    "Numbers": ("Numbers", "Num"),
    "Deuteronomy": ("Deuteronomy", "Deut"),
    "Joshua": ("Joshua", "Josh"),
    "Judges": ("Judges", "Judg"),
    "Ruth": ("Ruth",),
    "1 Samuel": ("1 Samuel", "1 Sam", "First Samuel"),
    "2 Samuel": ("2 Samuel", "2 Sam", "Second Samuel"),
    "1 Kings": ("1 Kings", "1 Kgs", "First Kings"),
    "2 Kings": ("2 Kings", "2 Kgs", "Second Kings"),
    "1 Chronicles": ("1 Chronicles", "1 Chron", "1 Chr", "First Chronicles"),
    "2 Chronicles": ("2 Chronicles", "2 Chron", "2 Chr", "Second Chronicles"),
    "Ezra": ("Ezra",),
    "Nehemiah": ("Nehemiah", "Neh"),
    "Esther": ("Esther", "Esth"),
    "Job": ("Job",),
    "Psalms": ("Psalms", "Psalm", "Ps"),
    "Proverbs": ("Proverbs", "Prov"),
    "Ecclesiastes": ("Ecclesiastes", "Eccl"),
    "Song of Solomon": ("Song of Solomon", "Song of Songs", "Song"),
    "Isaiah": ("Isaiah", "Isa"),
    "Jeremiah": ("Jeremiah", "Jer"),
    "Lamentations": ("Lamentations", "Lam"),
    "Ezekiel": ("Ezekiel", "Ezek"),
    "Daniel": ("Daniel", "Dan"),
    "Hosea": ("Hosea", "Hos"),
    "Joel": ("Joel",),
    "Amos": ("Amos",),
    "Obadiah": ("Obadiah", "Obad"),
    "Jonah": ("Jonah",),
    "Micah": ("Micah", "Mic"),
    "Nahum": ("Nahum", "Nah"),
    "Habakkuk": ("Habakkuk", "Hab"),
    "Zephaniah": ("Zephaniah", "Zeph"),
    "Haggai": ("Haggai", "Hag"),
    "Zechariah": ("Zechariah", "Zech"),
    "Malachi": ("Malachi", "Mal"),
    "Matthew": ("Matthew", "Matt"),
    "Mark": ("Mark",),
    "Luke": ("Luke",),
    "John": ("John",),
    "Acts": ("Acts",),
    "Romans": ("Romans", "Rom"),
    "1 Corinthians": ("1 Corinthians", "1 Cor", "First Corinthians"),
    "2 Corinthians": ("2 Corinthians", "2 Cor", "Second Corinthians"),
    "Galatians": ("Galatians", "Gal"),
    "Ephesians": ("Ephesians", "Eph"),
    "Philippians": ("Philippians", "Phil"),
    "Colossians": ("Colossians", "Col"),
    "1 Thessalonians": ("1 Thessalonians", "1 Thess", "First Thessalonians"),
    "2 Thessalonians": ("2 Thessalonians", "2 Thess", "Second Thessalonians"),
    "1 Timothy": ("1 Timothy", "1 Tim", "First Timothy"),
    "2 Timothy": ("2 Timothy", "2 Tim", "Second Timothy"),
    "Titus": ("Titus",),
    "Philemon": ("Philemon", "Phlm"),
    "Hebrews": ("Hebrews", "Heb"),
    "James": ("James", "Jas"),
    "1 Peter": ("1 Peter", "1 Pet", "First Peter"),
    "2 Peter": ("2 Peter", "2 Pet", "Second Peter"),
    "1 John": ("1 John", "First John"),
    "2 John": ("2 John", "Second John"),
    "3 John": ("3 John", "Third John"),
    "Jude": ("Jude",),
    "Revelation": ("Revelation", "Rev"),
}
OLD_TESTAMENT_BOOKS = frozenset(tuple(_BOOK_ALIASES)[:39])

_CHAPTER_COUNTS = dict(
    zip(
        _BOOK_ALIASES,
        (
            50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13,
            10, 42, 150, 31, 12, 8, 66, 52, 5, 48, 12, 14, 3, 9, 1, 4, 7, 3,
            3, 3, 2, 14, 4, 28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4, 5,
            3, 6, 4, 3, 1, 13, 5, 5, 3, 5, 1, 1, 1, 22,
        ),
        strict=True,
    )
)

_ALIAS_TO_BOOK = {
    re.sub(r"[.\s]+", " ", alias).strip().casefold(): book
    for book, aliases in _BOOK_ALIASES.items()
    for alias in aliases
}
_ALIAS_PATTERN = "|".join(
    re.escape(alias).replace(r"\ ", r"\s+") + r"\.?(?=\s)"
    for alias in sorted(
        (alias for aliases in _BOOK_ALIASES.values() for alias in aliases),
        key=len,
        reverse=True,
    )
)
_SCRIPTURE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9])(?P<book>{_ALIAS_PATTERN})\s+"
    r"(?P<chapter>\d{1,3})\s*:\s*(?P<verse_start>\d{1,3})"
    r"(?:\s*[-–—]\s*(?P<verse_end>\d{1,3}))?(?!\d)",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"\b[\w]+(?:['’][\w]+)?\b", re.UNICODE)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _load_sermon_source(
    extraction_path: Path,
) -> tuple[list[_SermonSegment], float, float]:
    try:
        payload = json.loads(extraction_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read extraction JSON {extraction_path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Extraction JSON is not an object: {extraction_path}")
    raw_segments = payload.get("segments")
    window = payload.get("sermon_window")
    if not isinstance(raw_segments, list) or not isinstance(window, dict):
        raise ValueError("Extraction has no sermon segments/window")

    start = _number(window.get("start_seconds"))
    end = _number(window.get("end_seconds"))
    if start is None or end is None or end <= start:
        raise ValueError("Extraction has no identified sermon window")

    included = window.get("included_segment_indexes")
    if isinstance(included, list) and all(
        isinstance(index, int) and not isinstance(index, bool) for index in included
    ):
        selected_indexes = list(dict.fromkeys(included))
    else:
        selected_indexes = []
        for index, item in enumerate(raw_segments):
            if not isinstance(item, dict):
                continue
            segment_start = _number(item.get("start_seconds"))
            segment_end = _number(item.get("end_seconds"))
            if segment_start is not None and segment_end is not None:
                if segment_end > start and segment_start < end:
                    selected_indexes.append(index)

    segments: list[_SermonSegment] = []
    for index in selected_indexes:
        if index < 0 or index >= len(raw_segments):
            raise ValueError(f"Invalid included sermon segment index: {index}")
        item = raw_segments[index]
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError(f"Sermon segment {index} has no text")
        segments.append(
            _SermonSegment(
                index=index,
                start_seconds=_number(item.get("start_seconds")),
                end_seconds=_number(item.get("end_seconds")),
                text=str(item["text"]),
            )
        )
    if not segments:
        raise ValueError("Identified sermon window contains no transcript segments")
    return segments, start, end - start


def _canonical_source(
    segments: list[_SermonSegment], sermon_start_seconds: float, duration_seconds: float
) -> bytes:
    payload = {
        "sermon_start_seconds": sermon_start_seconds,
        "duration_seconds": duration_seconds,
        "segments": [
            {
                "index": segment.index,
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "text": segment.text,
            }
            for segment in segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _reference_evidence(segments: list[_SermonSegment]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for segment in segments:
        for match in _SCRIPTURE_PATTERN.finditer(segment.text):
            alias = re.sub(r"[.\s]+", " ", match.group("book")).strip().casefold()
            book = _ALIAS_TO_BOOK.get(alias)
            if book is None:
                continue
            chapter = int(match.group("chapter"))
            verse_start = int(match.group("verse_start"))
            verse_end = int(match.group("verse_end") or verse_start)
            if not (1 <= chapter <= _CHAPTER_COUNTS[book]):
                continue
            if not (1 <= verse_start <= verse_end <= 176):
                continue
            canonical = f"{book} {chapter}:{verse_start}"
            if verse_end != verse_start:
                canonical += f"-{verse_end}"
            evidence.append(
                {
                    "book": book,
                    "chapter": chapter,
                    "verse_start": verse_start,
                    "verse_end": verse_end,
                    "canonical_reference": canonical,
                    "segment": segment,
                    "char_start": match.start(),
                    "char_end": match.end(),
                    "excerpt": match.group(0),
                }
            )
    return evidence


def analyze_sermon(
    database: Database,
    video: Video,
    *,
    analyzer_version: str = ANALYZER_VERSION,
) -> AnalysisOutcome:
    if not analyzer_version.strip():
        raise ValueError("Analyzer version must not be blank")
    extraction = database.get_latest_extraction_result_for_video(video.id)
    if extraction is None or extraction.proposed_json_path is None:
        raise ValueError(f"Video {video.youtube_video_id} has no identified sermon content")
    source_path = Path(extraction.proposed_json_path)
    segments, sermon_start_seconds, duration_seconds = _load_sermon_source(source_path)
    source_content_sha256 = _sha256(
        _canonical_source(segments, sermon_start_seconds, duration_seconds)
    )
    input_fingerprint = _sha256(
        json.dumps(
            {
                "analyzer_key": ANALYZER_KEY,
                "analyzer_version": analyzer_version,
                "schema_version": ANALYSIS_SCHEMA_VERSION,
                "source_content_sha256": source_content_sha256,
                "video_id": video.id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    references = _reference_evidence(segments)
    books = sorted({str(item["book"]) for item in references})
    passages = sorted({str(item["canonical_reference"]) for item in references})
    sermon_text = "\n".join(segment.text for segment in segments)
    measurement_values: list[tuple[str, object, str | None]] = [
        ("word_count", len(_WORD_PATTERN.findall(sermon_text)), "words"),
        ("sermon_start_seconds", sermon_start_seconds, "seconds"),
        ("sermon_duration_seconds", duration_seconds, "seconds"),
        ("scripture_reference_mentions", len(references), "mentions"),
        ("distinct_scripture_passages", len(passages), "passages"),
        ("distinct_scripture_books", len(books), "books"),
        ("scripture_books", books, None),
        ("scripture_detection_scope", "explicit_numeric_reference", None),
    ]
    measurements = [
        (key, json.dumps(value, sort_keys=True), unit)
        for key, value, unit in measurement_values
    ]

    evidence_rows = []
    for item in references:
        segment = item["segment"]
        assert isinstance(segment, _SermonSegment)
        payload = {
            "book": item["book"],
            "canonical_reference": item["canonical_reference"],
            "chapter": item["chapter"],
            "detection_class": "explicit",
            "detection_confidence": "high",
            "detection_method": "book_chapter_verse_pattern",
            "verse_end": item["verse_end"],
            "verse_start": item["verse_start"],
        }
        evidence_key = _sha256(
            json.dumps(
                {
                    **payload,
                    "segment_index": segment.index,
                    "char_start": item["char_start"],
                    "char_end": item["char_end"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        evidence_rows.append(
            (
                "scripture_reference",
                evidence_key,
                segment.index,
                segment.start_seconds,
                segment.end_seconds,
                int(item["char_start"]),
                int(item["char_end"]),
                str(item["excerpt"]),
                json.dumps(payload, sort_keys=True),
            )
        )

    run, created = database.add_sermon_analysis_run(
        video_id=video.id,
        extraction_result_id=extraction.id,
        analyzer_key=ANALYZER_KEY,
        analyzer_version=analyzer_version,
        source_kind="extraction_proposed_json",
        source_path=str(source_path),
        source_content_sha256=source_content_sha256,
        input_fingerprint=input_fingerprint,
        measurements=measurements,
        evidence=evidence_rows,
    )
    return AnalysisOutcome(run=run, created=created)
