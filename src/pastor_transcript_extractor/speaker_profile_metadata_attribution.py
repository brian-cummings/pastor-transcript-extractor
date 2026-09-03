from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from pastor_transcript_extractor.local_llm import LocalLlmClient, LocalLlmError
from pastor_transcript_extractor.speaker_registry import normalize_person_name
from pastor_transcript_extractor.storage import Database


PROFILE_METADATA_ATTRIBUTION_VERSION = "profile_metadata_attribution_v4"
PROFILE_METADATA_PROMPT_VERSION = "profile_metadata_name_consolidation_v3"
_SUPPORTED_ATTRIBUTION_VERSIONS = {
    "profile_metadata_attribution_v2",
    "profile_metadata_attribution_v3",
    PROFILE_METADATA_ATTRIBUTION_VERSION,
}
PROFILE_METADATA_OUTPUT_TOKEN_BUDGET = 768
PROFILE_METADATA_TEXT_LIMIT = 800
PROFILE_METADATA_TOTAL_TEXT_LIMIT = 14_000
_PROFILE_REASONS = {
    "reviewed_anonymous_speaker",
    "shadow_discovery_candidate",
}
_DECISIONS = {
    "propose_name",
    "insufficient_evidence",
    "conflicting_evidence",
    "invalid_metadata",
}
_REASON_CODES = {
    "consistent_speaker_credit",
    "repeated_name_across_recordings",
    "single_recording_only",
    "no_speaker_credit",
    "ambiguous_program_metadata",
    "multiple_candidate_names",
    "metadata_unavailable",
    "model_output_unverifiable",
}
_NON_PERSON_NAME_TOKENS = {
    "a",
    "advent",
    "an",
    "and",
    "baptist",
    "church",
    "divine",
    "fellowship",
    "in",
    "livestream",
    "message",
    "ministry",
    "of",
    "sabbath",
    "sermon",
    "service",
    "stream",
    "the",
    "to",
    "today",
    "events",
    "worship",
}
_PLACEHOLDER_NAMES = {
    "name",
    "none",
    "unknown",
    "speaker name",
}


@dataclass(frozen=True, slots=True)
class ProfileMetadataField:
    youtube_video_id: str
    field_path: str
    text: str


@dataclass(frozen=True, slots=True)
class ProfileMetadataInput:
    profile_id: int
    membership_fingerprint: str
    fields: tuple[ProfileMetadataField, ...]
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProfileMetadataEvidence:
    youtube_video_id: str
    field_path: str
    exact_excerpt: str


@dataclass(frozen=True, slots=True)
class ProfileMetadataAttribution:
    profile_id: int
    membership_fingerprint: str
    input_fingerprint: str
    decision: str
    routing: str
    proposed_name: str | None
    normalized_name: str | None
    reason_codes: tuple[str, ...]
    evidence: tuple[ProfileMetadataEvidence, ...]
    conflicting_names: tuple[str, ...]
    supporting_recording_count: int
    artifact_path: Path
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class ProfileMetadataFailure:
    profile_id: int
    input_fingerprint: str
    error_type: str
    error_message: str
    artifact_path: Path
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class ProfileMetadataAttributionRun:
    eligible: int
    proposed: int
    insufficient_evidence: int
    conflicting_evidence: int
    invalid_metadata: int
    cache_hits: int
    model_calls: int
    failed: int
    results: tuple[ProfileMetadataAttribution, ...]
    failures: tuple[ProfileMetadataFailure, ...]


def profile_metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": sorted(_DECISIONS)},
            "proposed_name": {"type": "string"},
            "reason_codes": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(_REASON_CODES)},
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "youtube_video_id": {"type": "string"},
                        "field_path": {"type": "string"},
                        "exact_excerpt": {"type": "string"},
                    },
                    "required": [
                        "youtube_video_id",
                        "field_path",
                        "exact_excerpt",
                    ],
                },
            },
            "conflicting_names": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "decision",
            "proposed_name",
            "reason_codes",
            "evidence",
            "conflicting_names",
        ],
    }


def profile_metadata_prompt(candidate: ProfileMetadataInput) -> str:
    records = [
        {
            "youtube_video_id": field.youtube_video_id,
            "field_path": field.field_path,
            "text": field.text,
        }
        for field in candidate.fields
    ]
    return (
        "Determine whether metadata from recordings already grouped into one "
        "acoustic speaker profile consistently credits one sermon speaker. "
        "Do not decide whether the recordings contain the same voice; that has "
        "already been established elsewhere. Channel names, church names, sermon "
        "subjects, quoted people, memorial honorees, musicians, and people merely "
        "thanked are not speaker credits. Prefer explicit forms such as 'sermon "
        "by NAME', 'with Pastor NAME', a sermon title followed by '| NAME', or "
        "repeated title bylines. Return propose_name only when the same full person "
        "name is supported by at least two distinct recordings with no conflict. "
        "Use insufficient_evidence when support is absent or occurs in only one "
        "recording. Use conflicting_evidence for competing plausible speaker "
        "names. The proposed spelling may omit an honorific or middle initial, "
        "but must otherwise name the person shown in the supplied metadata. Use "
        "invalid_metadata only when the supplied metadata cannot be interpreted. "
        "For propose_name, use only consistent_speaker_credit and "
        "repeated_name_across_recordings as reason codes and leave conflicting_names "
        "empty. For conflicting_evidence, cite at least two different full person "
        "names, include multiple_candidate_names, and ensure every conflicting name "
        "appears in a supplied evidence field. For insufficient_evidence, leave "
        "conflicting_names empty. Cite the exact video and field containing each "
        "name; copy a short exact excerpt when possible. PTE will independently "
        "ground names against the original field text. A church, city, program, "
        "worship service, placeholder "
        "such as NAME/Unknown/None, or channel is never a person. Never invent, "
        "expand initials, or infer a name from the source.\n\nMETADATA:\n"
        + json.dumps(records, indent=2, ensure_ascii=False)
    )


def build_profile_metadata_inputs(
    database: Database,
    *,
    profile_ids: frozenset[int] | None = None,
    model: str,
    model_digest: str,
) -> tuple[ProfileMetadataInput, ...]:
    candidate_ids = set(
        profile_metadata_candidate_profile_ids(
            database,
            profile_ids=profile_ids,
        )
    )
    if not candidate_ids:
        return ()
    candidates: list[ProfileMetadataInput] = []
    for profile in database.list_speaker_profiles():
        if profile.id not in candidate_ids:
            continue
        member_ids = database.list_effective_observation_ids_for_profile(
            profile.id
        )
        title_fields: list[ProfileMetadataField] = []
        supplemental_fields: list[ProfileMetadataField] = []
        member_fingerprints: list[str] = []
        metadata_fingerprints: list[dict[str, Any]] = []
        for observation_id in sorted(member_ids):
            observation = database.get_speaker_observation(observation_id)
            video = (
                database.get_video_by_id(observation.video_id)
                if observation is not None
                else None
            )
            if observation is None or video is None:
                continue
            member_fingerprints.append(observation.input_fingerprint)
            artifact = database.get_latest_metadata_artifact_for_video(video.id)
            metadata_fingerprints.append(
                {
                    "youtube_video_id": video.youtube_video_id,
                    "database_title": video.title,
                    "metadata_content_sha256": (
                        artifact.content_sha256 if artifact is not None else None
                    ),
                }
            )
            title_fields.append(
                ProfileMetadataField(
                    video.youtube_video_id,
                    "video.title",
                    _compact_text(video.title),
                )
            )
            if artifact is None:
                continue
            try:
                payload = json.loads(
                    Path(artifact.artifact_path).read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            supplemental_fields.extend(
                _artifact_fields(video.youtube_video_id, payload)
            )
        fields = _deduplicate_and_budget(
            (*title_fields, *supplemental_fields)
        )
        if not member_fingerprints:
            continue
        membership_fingerprint = _sha256(
            {
                "profile_id": profile.id,
                "observation_fingerprints": member_fingerprints,
            }
        )
        input_fingerprint = _sha256(
            {
                "version": PROFILE_METADATA_ATTRIBUTION_VERSION,
                "prompt_version": PROFILE_METADATA_PROMPT_VERSION,
                "profile_id": profile.id,
                "membership_fingerprint": membership_fingerprint,
                "metadata": metadata_fingerprints,
                "fields": [asdict(field) for field in fields],
                "model": model,
                "model_digest": model_digest,
            }
        )
        candidates.append(
            ProfileMetadataInput(
                profile.id,
                membership_fingerprint,
                tuple(fields),
                input_fingerprint,
            )
        )
    return tuple(candidates)


def profile_metadata_candidate_profile_ids(
    database: Database,
    *,
    profile_ids: frozenset[int] | None = None,
) -> tuple[int, ...]:
    claims = database.list_speaker_name_claims()
    explicit_names_by_observation: dict[int, set[str]] = {}
    for claim in claims:
        if (
            claim.observation_id is not None
            and claim.explicit_speaker_attribution
            and claim.normalized_name.strip()
        ):
            explicit_names_by_observation.setdefault(
                claim.observation_id, set()
            ).add(claim.normalized_name.strip())

    candidates: list[int] = []
    for profile in database.list_speaker_profiles():
        if (
            profile.created_reason not in _PROFILE_REASONS
            or database.resolve_speaker_profile_id(profile.id) != profile.id
            or (profile_ids is not None and profile.id not in profile_ids)
        ):
            continue
        member_ids = database.list_effective_observation_ids_for_profile(
            profile.id
        )
        if not member_ids or any(
            explicit_names_by_observation.get(observation_id)
            for observation_id in member_ids
        ):
            continue
        candidates.append(profile.id)
    return tuple(sorted(candidates))


def run_profile_metadata_attribution(
    database: Database,
    root: Path,
    client: LocalLlmClient,
    *,
    model_digest: str,
    profile_ids: frozenset[int] | None = None,
    progress_callback: Callable[[int, int, int, str], None] | None = None,
) -> ProfileMetadataAttributionRun:
    candidates = build_profile_metadata_inputs(
        database,
        profile_ids=profile_ids,
        model=client.model,
        model_digest=model_digest,
    )
    results: list[ProfileMetadataAttribution] = []
    failures: list[ProfileMetadataFailure] = []
    cache_hits = 0
    model_calls = 0
    failed = 0
    for index, candidate in enumerate(candidates, start=1):
        path = (
            root.expanduser().resolve()
            / f"profile-{candidate.profile_id}"
            / f"{candidate.input_fingerprint}.json"
        )
        attempt_path = path.with_suffix(".attempt.json")
        cached = _load_artifact(path, cache_hit=True)
        if cached is not None:
            cache_hits += 1
            results.append(cached)
            if progress_callback is not None:
                progress_callback(
                    index,
                    len(candidates),
                    candidate.profile_id,
                    f"cached:{cached.decision}",
                )
            continue
        cached_failure = _load_failure_artifact(
            attempt_path,
            candidate=candidate,
            cache_hit=True,
        )
        if cached_failure is not None:
            cache_hits += 1
            failed += 1
            failures.append(cached_failure)
            if progress_callback is not None:
                progress_callback(
                    index,
                    len(candidates),
                    candidate.profile_id,
                    "cached_failure:"
                    f"{cached_failure.error_type}: "
                    f"{cached_failure.error_message}",
                )
            continue
        model_calls += 1
        if progress_callback is not None:
            progress_callback(
                index,
                len(candidates),
                candidate.profile_id,
                "analyzing",
            )
        response = None
        try:
            response = client.generate_json(
                profile_metadata_prompt(candidate),
                profile_metadata_schema(),
                max_tokens=PROFILE_METADATA_OUTPUT_TOKEN_BUDGET,
            )
            if response.model != client.model:
                raise ValueError("metadata attribution model identity changed")
            validated = _validate_response(candidate, response.content)
        except (LocalLlmError, OSError, ValueError) as error:
            failed += 1
            failure = _write_failure_artifact(
                attempt_path,
                candidate=candidate,
                model=client.model,
                model_digest=model_digest,
                response=(response.content if response is not None else None),
                raw_response=(
                    response.raw_content if response is not None else None
                ),
                error=error,
            )
            failures.append(failure)
            if progress_callback is not None:
                progress_callback(
                    index,
                    len(candidates),
                    candidate.profile_id,
                    f"failed:{type(error).__name__}: {error}",
                )
            continue
        _write_success_attempt_artifact(
            attempt_path,
            candidate=candidate,
            model=client.model,
            model_digest=model_digest,
            response=response.content,
            raw_response=response.raw_content,
            validated=validated,
        )
        payload = {
            "schema_version": 1,
            "version": PROFILE_METADATA_ATTRIBUTION_VERSION,
            "prompt_version": PROFILE_METADATA_PROMPT_VERSION,
            "profile_id": candidate.profile_id,
            "membership_fingerprint": candidate.membership_fingerprint,
            "input_fingerprint": candidate.input_fingerprint,
            "model": client.model,
            "model_digest": model_digest,
            "result": validated,
            "result_sha256": _sha256(validated),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_artifact(path, payload)
        loaded = _load_artifact(path, cache_hit=False)
        if loaded is None:
            raise ValueError(f"could not replay metadata attribution: {path}")
        results.append(loaded)
        if progress_callback is not None:
            progress_callback(
                index,
                len(candidates),
                candidate.profile_id,
                loaded.decision,
            )
    counts = {decision: 0 for decision in _DECISIONS}
    for result in results:
        counts[result.decision] += 1
    return ProfileMetadataAttributionRun(
        eligible=len(candidates),
        proposed=counts["propose_name"],
        insufficient_evidence=counts["insufficient_evidence"],
        conflicting_evidence=counts["conflicting_evidence"],
        invalid_metadata=counts["invalid_metadata"],
        cache_hits=cache_hits,
        model_calls=model_calls,
        failed=failed,
        results=tuple(results),
        failures=tuple(failures),
    )


def load_profile_metadata_attributions(
    root: Path,
) -> dict[str, ProfileMetadataAttribution]:
    selected: dict[str, tuple[int, ProfileMetadataAttribution]] = {}
    if not root.is_dir():
        return {}
    for path in sorted(root.glob("profile-*/*.json")):
        result = _load_artifact(path, cache_hit=True)
        if result is None:
            continue
        try:
            modified = path.stat().st_mtime_ns
        except OSError:
            continue
        previous = selected.get(result.membership_fingerprint)
        if previous is None or modified > previous[0]:
            selected[result.membership_fingerprint] = (modified, result)
    return {fingerprint: item for fingerprint, (_, item) in selected.items()}


def _validate_response(
    candidate: ProfileMetadataInput,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    decision = payload.get("decision")
    proposed_name = payload.get("proposed_name")
    raw_reasons = payload.get("reason_codes")
    raw_evidence = payload.get("evidence")
    raw_conflicts = payload.get("conflicting_names")
    if (
        decision not in _DECISIONS
        or not isinstance(proposed_name, str)
        or not isinstance(raw_reasons, list)
        or not raw_reasons
        or any(reason not in _REASON_CODES for reason in raw_reasons)
        or not isinstance(raw_evidence, list)
        or not isinstance(raw_conflicts, list)
        or any(not isinstance(name, str) for name in raw_conflicts)
    ):
        raise ValueError("metadata attribution response shape is invalid")
    cited_evidence: list[dict[str, str]] = []
    fields = {
        (field.youtube_video_id, field.field_path): field.text
        for field in candidate.fields
    }
    for item in raw_evidence:
        if not isinstance(item, Mapping):
            raise ValueError("metadata attribution evidence is invalid")
        video_id = item.get("youtube_video_id")
        field_path = item.get("field_path")
        excerpt = item.get("exact_excerpt")
        if (
            not isinstance(video_id, str)
            or not isinstance(field_path, str)
            or not isinstance(excerpt, str)
            or (video_id, field_path) not in fields
        ):
            raise ValueError("metadata attribution evidence field is invalid")
        source_text = fields[(video_id, field_path)]
        grounded_excerpt = (
            excerpt.strip()
            if excerpt.strip() and excerpt.strip() in source_text
            else source_text[:240].strip()
        )
        if not grounded_excerpt:
            continue
        cited_evidence.append(
            {
                "youtube_video_id": video_id,
                "field_path": field_path,
                "exact_excerpt": grounded_excerpt,
            }
        )
    normalized_name = normalize_person_name(proposed_name)
    normalized_conflicts = {
        normalize_person_name(name): name.strip()
        for name in raw_conflicts
        if _valid_person_name(normalize_person_name(name), raw_name=name)
    }
    distinct_conflict_displays = {
        _proposal_display_name(name).casefold() for name in raw_conflicts
    }
    conflict_evidence, conflict_support = _ground_name_evidence(
        candidate,
        tuple(normalized_conflicts),
    )
    supported_conflicts = {
        name for name, recordings in conflict_support.items() if recordings
    }
    if (
        decision == "conflicting_evidence"
        and len(distinct_conflict_displays) == 1
        and len(normalized_conflicts) == 1
        and len(supported_conflicts) == 1
    ):
        normalized = next(iter(supported_conflicts))
        supporting_recordings = conflict_support[normalized]
        if len(supporting_recordings) >= 2:
            return {
                "decision": "propose_name",
                "routing": "human_confirmation_available",
                "proposed_name": _proposal_display_name(
                    normalized_conflicts[normalized]
                ),
                "normalized_name": normalized,
                "reason_codes": [
                    "consistent_speaker_credit",
                    "repeated_name_across_recordings",
                ],
                "evidence": conflict_evidence,
                "conflicting_names": [],
                "supporting_recording_count": len(supporting_recordings),
            }
    if len(supported_conflicts) >= 2:
        return {
            "decision": "conflicting_evidence",
            "routing": "human_review_required",
            "proposed_name": None,
            "normalized_name": None,
            "reason_codes": ["multiple_candidate_names"],
            "evidence": conflict_evidence,
            "conflicting_names": [
                normalized_conflicts[name]
                for name in sorted(supported_conflicts)
            ],
            "supporting_recording_count": len(
                {
                    video_id
                    for name in supported_conflicts
                    for video_id in conflict_support[name]
                }
            ),
        }
    if decision == "conflicting_evidence":
        decision = "insufficient_evidence"
        raw_reasons = ["ambiguous_program_metadata"]
    if decision == "propose_name":
        evidence, support = _ground_name_evidence(
            candidate,
            (normalized_name,),
        )
        supporting_recordings = support.get(normalized_name, set())
        if (
            not _valid_person_name(normalized_name, raw_name=proposed_name)
            or len(supporting_recordings) < 2
        ):
            raise ValueError("proposed name lacks independent metadata support")
        routing = "human_confirmation_available"
        normalized: str | None = normalized_name
        proposal: str | None = _proposal_display_name(proposed_name)
        raw_reasons = [
            "consistent_speaker_credit",
            "repeated_name_across_recordings",
        ]
    else:
        if decision == "insufficient_evidence":
            raw_reasons = [
                reason
                for reason in raw_reasons
                if reason
                in {
                    "single_recording_only",
                    "no_speaker_credit",
                    "ambiguous_program_metadata",
                    "metadata_unavailable",
                }
            ] or ["ambiguous_program_metadata"]
        routing = "human_review_required"
        normalized = None
        proposal = None
        evidence = cited_evidence
        supporting_recordings = set()
        raw_conflicts = []
    return {
        "decision": decision,
        "routing": routing,
        "proposed_name": proposal,
        "normalized_name": normalized,
        "reason_codes": list(dict.fromkeys(raw_reasons)),
        "evidence": evidence,
        "conflicting_names": list(dict.fromkeys(raw_conflicts)),
        "supporting_recording_count": len(supporting_recordings),
    }


def _ground_name_evidence(
    candidate: ProfileMetadataInput,
    normalized_names: Sequence[str],
) -> tuple[list[dict[str, str]], dict[str, set[str]]]:
    support = {name: set() for name in normalized_names}
    evidence: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for normalized_name in normalized_names:
        for field in candidate.fields:
            if field.field_path == "video.channel_name":
                continue
            span = _normalized_name_span(normalized_name, field.text)
            if span is None:
                continue
            support[normalized_name].add(field.youtube_video_id)
            key = (
                normalized_name,
                field.youtube_video_id,
                field.field_path,
            )
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "youtube_video_id": field.youtube_video_id,
                    "field_path": field.field_path,
                    "exact_excerpt": _exact_excerpt_window(
                        field.text,
                        start=span[0],
                        end=span[1],
                    ),
                }
            )
    return evidence, support


def _normalized_name_span(
    normalized_name: str,
    text: str,
) -> tuple[int, int] | None:
    name_tokens = normalized_name.split()
    if not name_tokens:
        return None
    text_tokens = tuple(
        (match.group(0), match.start(), match.end())
        for match in re.finditer(r"[a-z]+", text.casefold())
    )
    for start_index, (token, start, _end) in enumerate(text_tokens):
        if token != name_tokens[0]:
            continue
        text_index = start_index
        matched_end = text_tokens[start_index][2]
        for expected in name_tokens[1:]:
            text_index += 1
            while (
                text_index < len(text_tokens)
                and len(text_tokens[text_index][0]) == 1
                and text_tokens[text_index][0] != expected
            ):
                text_index += 1
            if (
                text_index >= len(text_tokens)
                or text_tokens[text_index][0] != expected
            ):
                break
            matched_end = text_tokens[text_index][2]
        else:
            return start, matched_end
    return None


def _exact_excerpt_window(
    text: str,
    *,
    start: int,
    end: int,
    radius: int = 80,
) -> str:
    window_start = max(0, start - radius)
    window_end = min(len(text), end + radius)
    return text[window_start:window_end].strip()


def _artifact_fields(
    youtube_video_id: str,
    payload: Mapping[str, Any],
) -> list[ProfileMetadataField]:
    fields: list[ProfileMetadataField] = []
    video = payload.get("video")
    if isinstance(video, Mapping) and isinstance(video.get("channel_name"), str):
        fields.append(
            ProfileMetadataField(
                youtube_video_id,
                "video.channel_name",
                _compact_text(str(video["channel_name"])),
            )
        )
    raw = payload.get("raw_metadata")
    if not isinstance(raw, Mapping):
        return fields
    for key in ("title", "description"):
        if isinstance(raw.get(key), str) and str(raw[key]).strip():
            fields.append(
                ProfileMetadataField(
                    youtube_video_id,
                    f"raw_metadata.{key}",
                    _compact_text(str(raw[key])),
                )
            )
    chapters = raw.get("chapters")
    if isinstance(chapters, Sequence) and not isinstance(chapters, (str, bytes)):
        for index, chapter in enumerate(chapters):
            if isinstance(chapter, Mapping) and isinstance(chapter.get("title"), str):
                fields.append(
                    ProfileMetadataField(
                        youtube_video_id,
                        f"raw_metadata.chapters[{index}].title",
                        _compact_text(str(chapter["title"])),
                    )
                )
    return fields


def _deduplicate_and_budget(
    fields: Sequence[ProfileMetadataField],
) -> list[ProfileMetadataField]:
    seen: set[tuple[str, str]] = set()
    selected: list[ProfileMetadataField] = []
    total = 0
    for field in fields:
        key = (field.youtube_video_id, field.text.casefold())
        if not field.text or key in seen:
            continue
        remaining = PROFILE_METADATA_TOTAL_TEXT_LIMIT - total
        if remaining <= 0:
            break
        text = field.text[:remaining]
        selected.append(
            ProfileMetadataField(field.youtube_video_id, field.field_path, text)
        )
        seen.add(key)
        total += len(text)
    return selected


def _compact_text(value: str) -> str:
    return " ".join(value.split())[:PROFILE_METADATA_TEXT_LIMIT]


def _valid_person_name(
    normalized_name: str,
    *,
    raw_name: str | None = None,
) -> bool:
    tokens = normalized_name.split()
    return (
        2 <= len(tokens) <= 5
        and (
            raw_name is None
            or not any(character.isdigit() for character in raw_name)
        )
        and normalized_name not in _PLACEHOLDER_NAMES
        and not any(token in _NON_PERSON_NAME_TOKENS for token in tokens)
    )


def _proposal_display_name(value: str) -> str:
    stripped = value.strip()
    without_pastor = re.sub(
        r"^pastor\b[\s,.:;\-–—]*",
        "",
        stripped,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    return without_pastor or stripped


def _load_artifact(
    path: Path,
    *,
    cache_hit: bool,
) -> ProfileMetadataAttribution | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    result = payload.get("result") if isinstance(payload, Mapping) else None
    if (
        payload.get("schema_version") != 1
        or payload.get("version") not in _SUPPORTED_ATTRIBUTION_VERSIONS
        or not isinstance(result, Mapping)
        or payload.get("result_sha256") != _sha256(result)
        or result.get("decision") not in _DECISIONS
        or result.get("routing")
        not in {"human_confirmation_available", "human_review_required"}
    ):
        return None
    try:
        evidence = tuple(
            ProfileMetadataEvidence(
                str(item["youtube_video_id"]),
                str(item["field_path"]),
                str(item["exact_excerpt"]),
            )
            for item in result.get("evidence", ())
            if isinstance(item, Mapping)
        )
        proposed_display_name = (
            _proposal_display_name(str(result["proposed_name"]))
            if isinstance(result.get("proposed_name"), str)
            else None
        )
        if (
            result.get("decision") == "propose_name"
            and proposed_display_name is not None
            and not _valid_person_name(
                normalize_person_name(proposed_display_name),
                raw_name=proposed_display_name,
            )
        ):
            return None
        return ProfileMetadataAttribution(
            profile_id=int(payload["profile_id"]),
            membership_fingerprint=str(payload["membership_fingerprint"]),
            input_fingerprint=str(payload["input_fingerprint"]),
            decision=str(result["decision"]),
            routing=str(result["routing"]),
            proposed_name=proposed_display_name,
            normalized_name=(
                normalize_person_name(proposed_display_name)
                if proposed_display_name is not None
                else str(result["normalized_name"])
                if isinstance(result.get("normalized_name"), str)
                else None
            ),
            reason_codes=tuple(str(item) for item in result.get("reason_codes", ())),
            evidence=evidence,
            conflicting_names=tuple(
                str(item) for item in result.get("conflicting_names", ())
            ),
            supporting_recording_count=int(
                result.get("supporting_recording_count", 0)
            ),
            artifact_path=path,
            cache_hit=cache_hit,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _load_failure_artifact(
    path: Path,
    *,
    candidate: ProfileMetadataInput,
    cache_hit: bool,
) -> ProfileMetadataFailure | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expected = payload.pop("attempt_sha256", None)
    if (
        payload.get("schema_version") != 1
        or payload.get("artifact_kind")
        != "profile_metadata_attribution_attempt"
        or payload.get("version") != PROFILE_METADATA_ATTRIBUTION_VERSION
        or payload.get("status") != "failed"
        or payload.get("cacheable") is not True
        or payload.get("profile_id") != candidate.profile_id
        or payload.get("input_fingerprint") != candidate.input_fingerprint
        or expected != _sha256(payload)
    ):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    try:
        return ProfileMetadataFailure(
            profile_id=candidate.profile_id,
            input_fingerprint=candidate.input_fingerprint,
            error_type=str(error["type"]),
            error_message=str(error["message"]),
            artifact_path=path,
            cache_hit=cache_hit,
        )
    except KeyError:
        return None


def _write_failure_artifact(
    path: Path,
    *,
    candidate: ProfileMetadataInput,
    model: str,
    model_digest: str,
    response: Mapping[str, Any] | None,
    raw_response: str | None,
    error: Exception,
) -> ProfileMetadataFailure:
    payload = _attempt_payload(
        candidate=candidate,
        model=model,
        model_digest=model_digest,
        status="failed",
        response=response,
        raw_response=raw_response,
        validated=None,
        error={"type": type(error).__name__, "message": str(error)},
    )
    _write_artifact(path, payload)
    return ProfileMetadataFailure(
        profile_id=candidate.profile_id,
        input_fingerprint=candidate.input_fingerprint,
        error_type=type(error).__name__,
        error_message=str(error),
        artifact_path=path,
        cache_hit=False,
    )


def _write_success_attempt_artifact(
    path: Path,
    *,
    candidate: ProfileMetadataInput,
    model: str,
    model_digest: str,
    response: Mapping[str, Any],
    raw_response: str,
    validated: Mapping[str, Any],
) -> None:
    _write_artifact(
        path,
        _attempt_payload(
            candidate=candidate,
            model=model,
            model_digest=model_digest,
            status="validated",
            response=response,
            raw_response=raw_response,
            validated=validated,
            error=None,
        ),
    )


def _attempt_payload(
    *,
    candidate: ProfileMetadataInput,
    model: str,
    model_digest: str,
    status: str,
    response: Mapping[str, Any] | None,
    raw_response: str | None,
    validated: Mapping[str, Any] | None,
    error: Mapping[str, str] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "profile_metadata_attribution_attempt",
        "version": PROFILE_METADATA_ATTRIBUTION_VERSION,
        "prompt_version": PROFILE_METADATA_PROMPT_VERSION,
        "profile_id": candidate.profile_id,
        "membership_fingerprint": candidate.membership_fingerprint,
        "input_fingerprint": candidate.input_fingerprint,
        "model": model,
        "model_digest": model_digest,
        "status": status,
        "cacheable": (
            error is not None and error.get("type") == "ValueError"
        ),
        "input_fields": [asdict(field) for field in candidate.fields],
        "response": dict(response) if response is not None else None,
        "raw_response": raw_response,
        "validated_result": (
            dict(validated) if validated is not None else None
        ),
        "error": dict(error) if error is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["attempt_sha256"] = _sha256(payload)
    return payload


def _write_artifact(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
