from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterable


NORMALIZER_VERSION = "rolling-caption-v1"
_WORD = re.compile(r"[^\w']+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class NormalizedCaptionText:
    text: str
    diagnostics: dict[str, Any]


def _words(text: str) -> list[str]:
    return [word for token in text.split() if (word := _WORD.sub("", token.casefold()))]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _suffix_prefix_overlap(left: list[str], right: list[str]) -> int:
    maximum = min(len(left), len(right))
    for size in range(maximum, 0, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


def normalize_caption_fragments(
    fragments: Iterable[tuple[int, str]],
) -> NormalizedCaptionText:
    """Normalize rolling captions for model prompts without changing source artifacts."""
    source = [(index, " ".join(text.split())) for index, text in fragments]
    raw_text = "\n".join(text for _, text in source)
    units: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []

    for source_index, text in source:
        words = _words(text)
        if not words:
            operations.append({"operation": "empty_fragment", "source_segment_index": source_index})
            continue

        previous = units[-1] if units else None
        if previous is not None and words == previous["words"]:
            previous["sources"].append(source_index)
            operations.append({"operation": "exact_duplicate", "source_segment_index": source_index})
            continue
        if previous is not None and len(words) >= len(previous["words"]) and words[: len(previous["words"])] == previous["words"]:
            previous["text"] = text
            previous["words"] = words
            previous["sources"].append(source_index)
            operations.append({"operation": "incremental_prefix_growth", "source_segment_index": source_index})
            continue
        if previous is not None and len(previous["words"]) >= len(words) and previous["words"][: len(words)] == words:
            previous["sources"].append(source_index)
            operations.append({"operation": "incremental_prefix_fragment", "source_segment_index": source_index})
            continue

        recent_words = [word for unit in units[-3:] for word in unit["words"]]
        if len(words) <= 8 and any(
            recent_words[position : position + len(words)] == words
            for position in range(max(0, len(recent_words) - len(words) + 1))
        ):
            if previous is not None:
                previous["sources"].append(source_index)
            operations.append({"operation": "repeated_short_fragment", "source_segment_index": source_index})
            continue

        overlap = _suffix_prefix_overlap(previous["words"], words) if previous is not None else 0
        overlap_is_meaningful = overlap >= 3 or (
            overlap >= 2 and overlap >= min(len(previous["words"]), len(words)) / 2
        )
        if previous is not None and overlap_is_meaningful:
            appended = text.split()[overlap:]
            if appended:
                previous["text"] = f"{previous['text']} {' '.join(appended)}"
                previous["words"].extend(words[overlap:])
            previous["sources"].append(source_index)
            operations.append({
                "operation": "suffix_prefix_overlap",
                "source_segment_index": source_index,
                "overlap_tokens": overlap,
            })
            continue

        units.append({"text": text, "words": words, "sources": [source_index]})

    normalized_text = "\n".join(unit["text"] for unit in units)
    raw_tokens = sum(len(_words(text)) for _, text in source)
    normalized_tokens = len(_words(normalized_text))
    diagnostics = {
        "normalizer_version": NORMALIZER_VERSION,
        "raw_text_hash": _hash(raw_text),
        "normalized_text_hash": _hash(normalized_text),
        "raw_token_count": raw_tokens,
        "normalized_token_count": normalized_tokens,
        "deduplication_ratio": round(
            1.0 - (normalized_tokens / raw_tokens), 6
        ) if raw_tokens else 0.0,
        "source_segment_indexes": [index for index, _ in source],
        "normalized_units": [
            {"source_segment_indexes": unit["sources"]} for unit in units
        ],
        "operations": operations,
    }
    return NormalizedCaptionText(normalized_text, diagnostics)


def normalize_caption_text(text: str) -> NormalizedCaptionText:
    return normalize_caption_fragments(enumerate(text.splitlines()))
