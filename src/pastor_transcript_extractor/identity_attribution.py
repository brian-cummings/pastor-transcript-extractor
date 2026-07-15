from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


ATTRIBUTION_EXTRACTOR_VERSION = "grounded_attribution_v2"
INTRO_CONTEXT_BEFORE_SECONDS = 300.0
INTRO_CONTEXT_AFTER_SECONDS = 180.0

_HONORIFIC_RE = re.compile(
    r"\b(?P<honorific>Pastor|Elder|Dr\.?|Pr\.?)\s+"
    r"(?P<name>[A-Z][A-Za-z'’-]+\s+[A-Z][A-Za-z'’-]+)\b"
)
_SPEAKER_IS_RE = re.compile(
    r"\b(?:our|the)?\s*(?:first |second |final )?(?:speaker|preacher)"
    r"(?:\s+for\s+today|\s+today|\s+this\s+(?:morning|evening))?\s+is\s+"
    r"(?:(?:Pastor|Elder|Dr\.?|Pr\.?)\s+)?"
    r"(?P<name>[A-Z][A-Za-z'’-]+\s+[A-Z][A-Za-z'’-]+)\b"
)
_MESSAGE_BY_RE = re.compile(
    r"(?i:\b(?:message|sermon|word)(?:\s+for\s+today)?[^.!?\n]{0,80}?\bby\s+)"
    r"(?:(?:Pastor|Elder|Dr\.?|Pr\.?)\s+)?"
    r"(?P<name>[A-Z][A-Za-z'’-]+\s+[A-Z][A-Za-z'’-]+)\b"
)
_TITLE_BYLINE_RE = re.compile(
    r"\bby\s+(?:(?:Pastor|Elder|Dr\.?|Pr\.?)\s+)?"
    r"(?P<name>[A-Z][A-Za-z'’-]+\s+[A-Z][A-Za-z'’-]+)\b"
)
_HONORIFICS = {"pastor", "elder", "dr", "pr"}
_MONTH_SUFFIX_RE = re.compile(
    r"-(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)$",
    re.IGNORECASE,
)
_OUTCOME_ORDER = (
    "explicit_guest_attribution",
    "explicit_target_attribution",
    "metadata_target_match",
    "metadata_non_target_match",
    "spoken_introduction_target",
    "spoken_introduction_guest",
    "conflicting_attribution",
    "no_attribution_evidence",
)


@dataclass(frozen=True, slots=True)
class AttributionResult:
    outcomes: tuple[str, ...]
    observations: tuple[dict[str, Any], ...]
    correlation_groups: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "extractor_version": ATTRIBUTION_EXTRACTOR_VERSION,
            "outcomes": list(self.outcomes),
            "observations": list(self.observations),
            "correlation_groups": list(self.correlation_groups),
            "independent_attribution_group_count": len(self.correlation_groups),
        }


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_person(value: str) -> str:
    tokens = re.findall(r"[a-z]+", value.lower())
    while tokens and tokens[0] in _HONORIFICS:
        tokens.pop(0)
    return " ".join(tokens)


def _target_pattern(target_name: str) -> re.Pattern[str] | None:
    tokens = re.findall(r"[A-Za-z'’-]+", target_name)
    while tokens and tokens[0].lower().rstrip(".") in _HONORIFICS:
        tokens.pop(0)
    if len(tokens) < 2:
        return None
    return re.compile(r"\b" + r"\s+".join(re.escape(token) for token in tokens) + r"\b", re.IGNORECASE)


def _exact_excerpt(text: str, start: int, end: int, radius: int = 120) -> str:
    if len(text) <= radius * 2:
        return text
    excerpt_start = max(0, start - radius)
    excerpt_end = min(len(text), end + radius)
    return text[excerpt_start:excerpt_end]


def _metadata_fields(payload: dict[str, Any]) -> Iterable[tuple[str, str]]:
    video = payload.get("video")
    if isinstance(video, dict) and isinstance(video.get("title"), str):
        yield "video.title", str(video["title"])
    raw = payload.get("raw_metadata")
    if not isinstance(raw, dict):
        return
    for field in ("title", "description"):
        if isinstance(raw.get(field), str):
            yield f"raw_metadata.{field}", str(raw[field])
    chapters = raw.get("chapters")
    if isinstance(chapters, list):
        for index, chapter in enumerate(chapters):
            if isinstance(chapter, dict) and isinstance(chapter.get("title"), str):
                yield f"raw_metadata.chapters[{index}].title", str(chapter["title"])


def _candidate_mentions(text: str, target_name: str) -> list[tuple[str, int, int]]:
    candidates: list[tuple[str, int, int]] = []
    target_pattern = _target_pattern(target_name)
    if target_pattern is not None:
        for match in target_pattern.finditer(text):
            candidates.append((match.group(0), match.start(), match.end()))
    for pattern in (_HONORIFIC_RE, _SPEAKER_IS_RE, _MESSAGE_BY_RE, _TITLE_BYLINE_RE):
        for match in pattern.finditer(text):
            name = match.group("name")
            start, end = match.span("name")
            cleaned_name = _MONTH_SUFFIX_RE.sub("", name)
            if cleaned_name != name:
                end -= len(name) - len(cleaned_name)
                name = cleaned_name
            if not any(existing_start == start and existing_end == end for _, existing_start, existing_end in candidates):
                candidates.append((name, start, end))
    return sorted(candidates, key=lambda item: (item[1], item[2]))


def _metadata_is_explicit(field_path: str, text: str, name_start: int, name_end: int) -> bool:
    prefix = text[:name_start].lower()
    if field_path.endswith("title"):
        if re.search(r"\bby\s+(?:(?:pastor|elder|dr\.?|pr\.?)\s+)?$", prefix):
            return True
        if re.search(r"(?:^|[-|–—:])\s*(?:(?:pastor|elder|dr\.?|pr\.?)\s+)?$", prefix):
            return True
    context_start = max(0, name_start - 140)
    context = text[context_start:min(len(text), name_end + 140)]
    local_start = name_start - context_start
    local_end = local_start + (name_end - name_start)
    marked = context[:local_start] + " <name> " + context[local_end:]
    normalized = " ".join(marked.lower().split())
    titled_name = r"(?:(?:pastor|elder|dr\.?|pr\.?) )?<name>"
    return any(
        re.search(pattern, normalized)
        for pattern in (
            rf"\b(?:message|sermon|word).{{0,80}}\b(?:by|presented by|delivered by|brought by) {titled_name}",
            rf"\b(?:speaker|preacher)(?: is|:)? {titled_name}",
            r"\b<name> .{0,80}\b(?:is the speaker|is our speaker|will bring|will deliver|will present|will preach)",
        )
    )


def _spoken_is_explicit(text: str, name_start: int, name_end: int) -> bool:
    context = text[max(0, name_start - 180):min(len(text), name_end + 180)]
    local_start = min(180, name_start)
    local_end = local_start + (name_end - name_start)
    marked = context[:local_start] + " <name> " + context[local_end:]
    normalized = " ".join(marked.lower().split())
    titled_name = r"(?:(?:pastor|elder|dr\.?|pr\.?) )?<name>"
    patterns = (
        rf"\b(?:our|the) (?:speaker|preacher)(?: for today| today| this morning| this evening)? is {titled_name}",
        rf"\b(?:first|second|final) speaker is {titled_name}",
        rf"\b(?:message|sermon|word)(?: for today)? .{{0,80}}\bby {titled_name}",
        r"\b<name> .{0,80}\b(?:bring|deliver|present|preach).{0,40}\b(?:message|sermon|word)",
        r"\b(?:introduce|present) .{0,80}\b(?:speaker|preacher).{0,40}<name>",
        r"\b(?:introduce|present) .{0,40}<name>.{0,80}\b(?:speaker|preacher|pulpit|message)",
        rf"\bwelcome {titled_name} .{{0,60}}\b(?:pulpit|message|sermon)",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _intro_segments(proposed: dict[str, Any]) -> Iterable[tuple[int, dict[str, Any]]]:
    segments = proposed.get("segments")
    if not isinstance(segments, list):
        return
    window = proposed.get("sermon_window")
    start = window.get("start_seconds") if isinstance(window, dict) else None
    has_effective_start = isinstance(start, (int, float))
    start_seconds = float(start) if has_effective_start else 0.0
    lower = max(0.0, start_seconds - INTRO_CONTEXT_BEFORE_SECONDS)
    upper = start_seconds + INTRO_CONTEXT_AFTER_SECONDS
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            continue
        segment_start = segment.get("start_seconds")
        segment_end = segment.get("end_seconds")
        if not isinstance(segment_start, (int, float)) or not isinstance(segment_end, (int, float)):
            continue
        if not has_effective_start or (float(segment_end) > lower and float(segment_start) < upper):
            yield index, segment


def extract_grounded_attributions(
    *,
    metadata_payload: dict[str, Any],
    proposed_payload: dict[str, Any],
    target_name: str,
    metadata_artifact_id: int,
    metadata_content_sha256: str,
) -> AttributionResult:
    """Extract only exact, attributable names; never infer identity from content style."""
    target_normalized = _normalized_person(target_name)
    observations: list[dict[str, Any]] = []

    for field_path, text in _metadata_fields(metadata_payload):
        for name, start, end in _candidate_mentions(text, target_name):
            normalized = _normalized_person(name)
            if not normalized:
                continue
            person_kind = "target" if normalized == target_normalized else "non_target"
            observations.append({
                "channel": "metadata",
                "signal_type": f"metadata_{person_kind}_match",
                "person_kind": person_kind,
                "person_name": name,
                "normalized_person_name": normalized,
                "explicit_speaker_attribution": _metadata_is_explicit(field_path, text, start, end),
                "correlation_group_id": "speaker-credit-" + _canonical_hash(normalized)[:12],
                "provenance": {
                    "metadata_artifact_id": metadata_artifact_id,
                    "metadata_content_sha256": metadata_content_sha256,
                    "metadata_source_kind": metadata_payload.get("source_kind"),
                    "field_path": field_path,
                    "exact_excerpt": _exact_excerpt(text, start, end),
                    "match_start": start,
                    "match_end": end,
                },
            })

    for index, segment in _intro_segments(proposed_payload):
        text = str(segment["text"])
        for name, start, end in _candidate_mentions(text, target_name):
            if not _spoken_is_explicit(text, start, end):
                continue
            normalized = _normalized_person(name)
            if not normalized:
                continue
            person_kind = "target" if normalized == target_normalized else "non_target"
            observations.append({
                "channel": "spoken",
                "signal_type": f"spoken_introduction_{'target' if person_kind == 'target' else 'guest'}",
                "person_kind": person_kind,
                "person_name": name,
                "normalized_person_name": normalized,
                "explicit_speaker_attribution": True,
                "correlation_group_id": "speaker-credit-" + _canonical_hash(normalized)[:12],
                "provenance": {
                    "line_id": f"S{index + 1:06d}",
                    "segment_index": index,
                    "start_seconds": segment.get("start_seconds"),
                    "end_seconds": segment.get("end_seconds"),
                    "exact_excerpt": _exact_excerpt(text, start, end),
                    "match_start": start,
                    "match_end": end,
                },
            })

    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        key = _canonical_hash({
            "signal_type": observation["signal_type"],
            "person": observation["normalized_person_name"],
            "provenance": observation["provenance"],
        })
        if key not in seen:
            seen.add(key)
            deduplicated.append(observation)

    collapsed: list[dict[str, Any]] = []
    for observation in deduplicated:
        if observation["channel"] != "spoken":
            collapsed.append(observation)
            continue
        start_seconds = observation["provenance"].get("start_seconds")
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(collapsed)
                if existing["channel"] == "spoken"
                and existing["normalized_person_name"] == observation["normalized_person_name"]
                and isinstance(existing["provenance"].get("start_seconds"), (int, float))
                and isinstance(start_seconds, (int, float))
                and abs(float(existing["provenance"]["start_seconds"]) - float(start_seconds)) <= 10.0
            ),
            None,
        )
        if duplicate_index is None:
            collapsed.append(observation)
            continue
        existing_excerpt = str(collapsed[duplicate_index]["provenance"].get("exact_excerpt", ""))
        new_excerpt = str(observation["provenance"].get("exact_excerpt", ""))
        if len(new_excerpt) > len(existing_excerpt):
            collapsed[duplicate_index] = observation
    deduplicated = collapsed

    grouped: dict[str, list[dict[str, Any]]] = {}
    for observation in deduplicated:
        grouped.setdefault(str(observation["correlation_group_id"]), []).append(observation)
    correlation_groups = [
        {
            "correlation_group_id": group_id,
            "normalized_person_name": items[0]["normalized_person_name"],
            "person_kind": items[0]["person_kind"],
            "observation_count": len(items),
            "channels": sorted({str(item["channel"]) for item in items}),
            "signal_types": sorted({str(item["signal_type"]) for item in items}),
            "counts_as_independent_evidence": 1,
        }
        for group_id, items in sorted(grouped.items())
    ]

    target_observations = [item for item in deduplicated if item["person_kind"] == "target"]
    guest_observations = [item for item in deduplicated if item["person_kind"] == "non_target"]
    outcomes: set[str] = set()
    if any(item["channel"] == "metadata" for item in target_observations):
        outcomes.add("metadata_target_match")
    if any(item["channel"] == "metadata" for item in guest_observations):
        outcomes.add("metadata_non_target_match")
    if any(item["signal_type"] == "spoken_introduction_target" for item in target_observations):
        outcomes.add("spoken_introduction_target")
    if any(item["signal_type"] == "spoken_introduction_guest" for item in guest_observations):
        outcomes.add("spoken_introduction_guest")
    if any(item["explicit_speaker_attribution"] for item in target_observations):
        outcomes.add("explicit_target_attribution")
    if any(item["explicit_speaker_attribution"] for item in guest_observations):
        outcomes.add("explicit_guest_attribution")
    if (
        any(item["explicit_speaker_attribution"] for item in target_observations)
        and any(item["explicit_speaker_attribution"] for item in guest_observations)
    ):
        outcomes.add("conflicting_attribution")
    if not deduplicated:
        outcomes.add("no_attribution_evidence")

    ordered_outcomes = tuple(outcome for outcome in _OUTCOME_ORDER if outcome in outcomes)
    return AttributionResult(
        outcomes=ordered_outcomes,
        observations=tuple(deduplicated),
        correlation_groups=tuple(correlation_groups),
    )
